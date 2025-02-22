from collections import defaultdict
import os
import itertools
from typing import Optional, Generator, Dict, List, Any, Callable, Union, Tuple, Iterable
import time

import gymnasium
import gymnasium.spaces
import gymnasium.vector
import torch
from torch.utils.data.dataloader import default_collate
import torch.nn
import torch.nn.utils
import numpy as np
import numpy.typing as npt
import wandb

from frankenstein.buffer.vec_history import VecHistoryBuffer
from frankenstein.advantage.gae import generalized_advantage_estimate 
from frankenstein.loss.policy_gradient import clipped_advantage_policy_gradient_loss

from big_rl.minigrid.envs import make_env
from big_rl.utils import torch_save, zip2, merge_space, generate_id
from big_rl.minigrid.common import init_model, env_config_presets


def compute_ppo_losses(
        history : VecHistoryBuffer,
        model : torch.nn.Module,
        preprocess_input_fn: Optional[Callable],
        discount : float,
        gae_lambda : float,
        norm_adv : bool,
        clip_vf_loss : Optional[float],
        entropy_loss_coeff : float,
        vf_loss_coeff : float,
        target_kl : Optional[float],
        num_epochs : int) -> Generator[Dict[str,Union[torch.Tensor,Tuple[torch.Tensor,...]]],None,None]:
    """
    Compute the losses for PPO.
    """
    obs = history.obs
    action = history.action
    reward = history.reward
    terminal = history.terminal
    misc = history.misc
    assert isinstance(misc,dict)
    hidden = misc['hidden']

    n = len(history.obs_history)
    num_training_envs = len(reward[0])
    initial_hidden = model.init_hidden(num_training_envs) # type: ignore

    with torch.no_grad():
        net_output = []
        curr_hidden = tuple([h[0].detach() for h in hidden])
        for o,term in zip2(obs,terminal):
            curr_hidden = tuple([
                torch.where(term.unsqueeze(1), init_h, h)
                for init_h,h in zip(initial_hidden,curr_hidden)
            ])
            o = preprocess_input_fn(o) if preprocess_input_fn is not None else o
            no = model(o,curr_hidden)
            curr_hidden = no['hidden']
            net_output.append(no)
        net_output = default_collate(net_output)
        state_values_old = net_output['value'].squeeze(2)
        action_dist = torch.distributions.Categorical(logits=net_output['action'][:n-1])
        log_action_probs_old = action_dist.log_prob(action)

        # Advantage
        advantages = generalized_advantage_estimate(
                state_values = state_values_old[:n-1,:],
                next_state_values = state_values_old[1:,:],
                rewards = reward[1:,:],
                terminals = terminal[1:,:],
                discount = discount,
                gae_lambda = gae_lambda,
        )
        returns = advantages + state_values_old[:n-1,:]

        if norm_adv:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    for _ in range(num_epochs):
        net_output = []
        curr_hidden = tuple([h[0].detach() for h in hidden])
        initial_hidden = model.init_hidden(num_training_envs) # type: ignore
        for o,term in zip2(obs,terminal):
            curr_hidden = tuple([
                torch.where(term.unsqueeze(1), init_h, h)
                for init_h,h in zip(initial_hidden,curr_hidden)
            ])
            o = preprocess_input_fn(o) if preprocess_input_fn is not None else o
            no = model(o,curr_hidden)
            curr_hidden = no['hidden']
            net_output.append(no)
        net_output = default_collate(net_output)

        assert 'value' in net_output
        assert 'action' in net_output
        state_values = net_output['value'].squeeze()
        action_dist = torch.distributions.Categorical(logits=net_output['action'][:n-1])
        log_action_probs = action_dist.log_prob(action)
        entropy = action_dist.entropy()

        with torch.no_grad():
            logratio = log_action_probs - log_action_probs_old
            ratio = logratio.exp()
            approx_kl = ((ratio - 1) - logratio).mean()

        # Policy loss
        pg_loss = clipped_advantage_policy_gradient_loss(
                log_action_probs = log_action_probs,
                old_log_action_probs = log_action_probs_old,
                advantages = advantages,
                terminals = terminal[:n-1],
                epsilon=0.1
        ).mean()

        # Value loss
        if clip_vf_loss is not None:
            v_loss_unclipped = (state_values[:n-1] - returns) ** 2
            v_clipped = state_values_old[:n-1] + torch.clamp(
                state_values[:n-1] - state_values_old[:n-1],
                -clip_vf_loss,
                clip_vf_loss,
            )
            v_loss_clipped = (v_clipped - returns) ** 2
            v_loss_max = torch.max(v_loss_unclipped, v_loss_clipped)
            v_loss = 0.5 * v_loss_max.mean()
        else:
            v_loss = 0.5 * ((state_values[:n-1] - returns) ** 2).mean()

        entropy_loss = entropy.mean()
        loss = pg_loss - entropy_loss_coeff * entropy_loss + v_loss * vf_loss_coeff

        yield {
                'loss': loss,
                'loss_pi': pg_loss,
                'loss_vf': v_loss,
                'loss_entropy': -entropy_loss,
                'approx_kl': approx_kl,
                'output': net_output,
                'hidden': tuple(h.detach() for h in curr_hidden),
        }

        if target_kl is not None:
            if approx_kl > target_kl:
                break


class MultitaskDynamicWeight:
    def __init__(self, max_score, random_score, temperature=1.0, ema_weight=0.99):
        self._max_score = np.array(max_score)
        self._random_score = np.array(random_score)
        self._temperature = temperature
        self._ema_weight = ema_weight

        self._score = np.array(random_score)

    def step(self, scores: Iterable[Iterable[float]]):
        for i,task_scores in enumerate(scores):
            for s in task_scores:
                self._score[i] = self._score[i] * self._ema_weight + s * (1 - self._ema_weight)

    @property
    def weight(self):
        relative_score = -(self._score - self._random_score) / (self._max_score - self._random_score)
        x = np.exp(relative_score / self._temperature)
        return x / x.sum()


class MultitaskStaticWeight:
    def __init__(self, weight):
        for w in weight:
            assert w >= 0, 'weight must be non-negative'
        if isinstance(weight, torch.Tensor):
            self._weight = weight.clone() / weight.sum()
        else:
            self._weight = torch.tensor(weight, dtype=torch.float)
            self._weight /= self._weight.sum()

    def step(self, scores: Iterable[Iterable[float]]):
        ...

    @property
    def weight(self):
        return self._weight


def log_episode_end(done, info, episode_reward, episode_true_reward, episode_steps, env_ids, env_label_to_id, global_step_counter):
    for env_label, env_id in env_label_to_id.items():
        done2 = done & (env_ids == env_id)
        if not done2.any():
            continue
        fi = info['_final_info']
        unsupervised_trials = np.array([x['unsupervised_trials'] for x in info['final_info'][fi]])
        supervised_trials = np.array([x['supervised_trials'] for x in info['final_info'][fi]])
        unsupervised_reward = np.array([x['unsupervised_reward'] for x in info['final_info'][fi]])
        supervised_reward = np.array([x['supervised_reward'] for x in info['final_info'][fi]])
        if wandb.run is not None:
            data = {
                    f'reward/{env_label}': episode_reward[done2].mean().item(),
                    f'true_reward/{env_label}': episode_true_reward[done2].mean().item(),
                    f'episode_length/{env_label}': episode_steps[done2].mean().item(),
                    'step': global_step_counter[0]-global_step_counter[1],
                    'step_total': global_step_counter[0],
            }
            data[f'unsupervised_trials/{env_label}'] = unsupervised_trials[done2[fi]].mean().item()
            data[f'supervised_trials/{env_label}'] = supervised_trials[done2[fi]].mean().item()
            if unsupervised_trials[done2[fi]].mean() > 0:
                data[f'unsupervised_reward/{env_label}'] = unsupervised_reward[done2[fi]].mean().item()
            if supervised_trials[done2[fi]].mean() > 0:
                data[f'supervised_reward/{env_label}'] = supervised_reward[done2[fi]].mean().item()
            wandb.log(data, step = global_step_counter[0])
        print(f'  reward: {episode_reward[done].mean():.2f}\t len: {episode_steps[done].mean()} \t env: {env_label} ({done2.sum().item()})')


def train_single_env(
        global_step_counter: List[int],
        model: torch.nn.Module,
        env: gymnasium.vector.VectorEnv,
        env_labels: List[str],
        *,
        obs_scale: Dict[str,float] = {},
        obs_ignore: List[str] = ['obs (mission)'],
        rollout_length: int = 128,
        reward_scale: float = 1.0,
        reward_clip: Optional[float] = 1.0,
        discount: float = 0.99,
        gae_lambda: float = 0.95,
        clip_vf_loss: Optional[float] = None,
        entropy_loss_coeff: float = 0.01,
        vf_loss_coeff: float = 0.5,
        num_epochs: int = 4,
        target_kl: Optional[float] = None,
        norm_adv: bool = True,
        warmup_steps: int = 0,
        update_hidden_after_grad: bool = False,
        ) -> Generator[Dict[str, Any], None, None]:
    """
    Train a model with PPO on an Atari game.

    Args:
        model: ...
        env: `gym.vector.VectorEnv`
    """
    num_envs = env.num_envs

    env_label_to_id = {label: i for i,label in enumerate(set(env_labels))}
    env_ids = np.array([env_label_to_id[label] for label in env_labels])

    device = next(model.parameters()).device

    def preprocess_input(obs: Dict[str, Any]) -> Dict[str, torch.Tensor]:
        return {
            k: torch.tensor(v, device=device)*obs_scale.get(k,1)
            for k,v in obs.items() if k not in obs_ignore
        }

    history = VecHistoryBuffer(
            num_envs = num_envs,
            max_len=rollout_length+1,
            device=device)
    log = {}

    obs, info = env.reset(seed=0)
    hidden = model.init_hidden(num_envs) # type: ignore (???)
    history.append_obs(
            {k:v for k,v in obs.items() if k not in obs_ignore},
            misc = {'hidden': hidden},
    )
    episode_true_reward = np.zeros(num_envs) # Actual reward we want to optimize before any modifications (e.g. clipping)
    episode_reward = np.zeros(num_envs) # Reward presented to the learning algorithm
    episode_steps = np.zeros(num_envs)

    ##################################################
    # Warmup
    # The state of all environments are similar at the start of an episode. By warming up, we increase the diversity of states to something that is closer to iid.

    start_time = time.time()
    warmup_episode_rewards = defaultdict(lambda: [])
    warmup_episode_steps = defaultdict(lambda: [])
    for _ in range(warmup_steps):
        # Select action
        with torch.no_grad():
            model_output = model({
                k: torch.tensor(v, dtype=torch.float, device=device)*obs_scale.get(k,1)
                for k,v in obs.items()
                if k not in obs_ignore
            }, hidden)
            hidden = model_output['hidden']

            action_probs = model_output['action'].softmax(1)
            action_dist = torch.distributions.Categorical(action_probs)
            action = action_dist.sample().cpu().numpy()

        # Step environment
        obs, reward, terminated, truncated, info = env.step(action) # type: ignore
        done = terminated | truncated

        episode_reward += reward
        episode_true_reward += info.get('reward', reward)
        episode_steps += 1

        if done.any():
            # Reset hidden state for finished episodes
            hidden = tuple(
                    torch.where(torch.tensor(done, device=device).unsqueeze(1), h0, h)
                    for h0,h in zip(model.init_hidden(num_envs), hidden) # type: ignore (???)
            )
            # Print stats
            for env_label, env_id in env_label_to_id.items():
                done2 = done & (env_ids == env_id)
                if not done2.any():
                    continue
                for x in episode_reward[done2]:
                    warmup_episode_rewards[env_label].append(x.item())
                for x in episode_steps[done2]:
                    warmup_episode_steps[env_label].append(x.item())
                print(f'Warmup\t reward: {episode_reward[done2].mean():.2f}\t len: {episode_steps[done2].mean()} \t env: {env_label} ({done2.sum().item()})')
            # Reset episode stats
            episode_reward[done] = 0
            episode_true_reward[done] = 0
            episode_steps[done] = 0

    if warmup_steps > 0:
        print(f'Warmup time: {time.time() - start_time:.2f} s')
        for env_label, env_id in env_label_to_id.items():
            reward_mean = np.mean(warmup_episode_rewards[env_label])
            reward_std = np.std(warmup_episode_rewards[env_label])
            steps_mean = np.mean(warmup_episode_steps[env_label])
            # TODO: handle case where there are no completed episodes during warmup?
            if wandb.run is not None:
                wandb.log({
                    f'reward/{env_label}': reward_mean,
                    f'episode_length/{env_label}': steps_mean,
                    'step': global_step_counter[0]-global_step_counter[1],
                    'step_total': global_step_counter[0],
                }, step = global_step_counter[0])
            print(f'\t{env_label}\treward: {reward_mean:.2f} +/- {reward_std:.2f}\t len: {steps_mean:.2f}')

    ##################################################
    # Start training
    for step in itertools.count():
        # Gather data
        state_values = [] # For logging purposes
        entropies = [] # For logging purposes
        episode_rewards = [] # For multitask weighing purposes
        for _ in range(rollout_length):
            global_step_counter[0] += num_envs

            # Select action
            with torch.no_grad():
                model_output = model({
                    k: torch.tensor(v, dtype=torch.float, device=device)*obs_scale.get(k,1)
                    for k,v in obs.items()
                    if k not in obs_ignore
                }, hidden)
                hidden = model_output['hidden']

                action_probs = model_output['action'].softmax(1)
                action_dist = torch.distributions.Categorical(action_probs)
                action = action_dist.sample().cpu().numpy()

                state_values.append(model_output['value'])
                entropies.append(action_dist.entropy())

            # Step environment
            obs, reward, terminated, truncated, info = env.step(action) # type: ignore
            done = terminated | truncated

            history.append_action(action)
            episode_reward += reward
            episode_true_reward += info.get('reward', reward)
            episode_steps += 1

            reward *= reward_scale
            if reward_clip is not None:
                reward = np.clip(reward, -reward_clip, reward_clip)

            history.append_obs(
                    {k:v for k,v in obs.items() if k not in obs_ignore}, reward, done,
                    misc = {'hidden': hidden}
            )

            if done.any():
                print(f'Episode finished ({step * num_envs * rollout_length:,} -- {global_step_counter[0]:,})')
                log_episode_end(
                        done = done,
                        info = info,
                        episode_reward = episode_reward,
                        episode_true_reward = episode_true_reward,
                        episode_steps = episode_steps,
                        env_ids = env_ids,
                        env_label_to_id = env_label_to_id,
                        global_step_counter = global_step_counter,
                )
                # Reset hidden state for finished episodes
                hidden = tuple(
                        torch.where(torch.tensor(done, device=device).unsqueeze(1), h0, h)
                        for h0,h in zip(model.init_hidden(num_envs), hidden) # type: ignore (???)
                )
                # Save episode rewards
                for r in episode_reward[done]:
                    episode_rewards.append(r)
                # Reset episode stats
                episode_reward[done] = 0
                episode_true_reward[done] = 0
                episode_steps[done] = 0

        if type(model).__name__ == 'ModularPolicy5':
            assert isinstance(model.last_attention, list)
            assert isinstance(model.last_input_labels, list)
            assert isinstance(model.last_output_attention, dict)
            log['attention max'] = {
                label: max([a.max().item() for a in attn])
                for label, attn in
                zip(model.last_input_labels,
                    zip(
                        model.last_attention[0].split(1,dim=2),
                        model.last_output_attention['action'].split(1,dim=1), # type: ignore (???)
                        model.last_output_attention['value'].split(1,dim=1), # type: ignore (???)
                    )
                )
            }

        # Train
        losses = compute_ppo_losses(
                history = history,
                model = model,
                preprocess_input_fn = preprocess_input,
                discount = discount,
                gae_lambda = gae_lambda,
                norm_adv = norm_adv,
                clip_vf_loss = clip_vf_loss,
                vf_loss_coeff = vf_loss_coeff,
                entropy_loss_coeff = entropy_loss_coeff,
                target_kl = target_kl,
                num_epochs = num_epochs,
        )
        x = None
        for x in losses:
            log['state_value'] = torch.stack(state_values)
            log['entropy'] = torch.stack(entropies)

            yield {
                'log': log,
                'episode_rewards': episode_rewards,
                **x
            }

            log = {}

        # Clear data
        history.clear()
        episode_rewards = []

        # Update hidden state
        if x is not None and update_hidden_after_grad:
            history.misc_history[-1]['hidden'] = x['hidden']
            hidden = x['hidden']


def train(
        model: torch.nn.Module,
        envs: List[gymnasium.vector.VectorEnv],
        env_labels: List[List[str]],
        env_group_labels: List[str],
        optimizer: torch.optim.Optimizer,
        lr_scheduler: Optional[torch.optim.lr_scheduler._LRScheduler], # XXX: Private class. This might break in the future.
        *,
        max_steps: int = 1000,
        max_steps_total: int = -1,
        rollout_length: int = 128,
        obs_scale: Dict[str,float] = {},
        reward_scale: float = 1.0,
        reward_clip: Optional[float] = 1.0,
        max_grad_norm: float = 0.5,
        discount: float = 0.99,
        gae_lambda: float = 0.95,
        clip_vf_loss: Optional[float] = None,
        entropy_loss_coeff: float = 0.01,
        vf_loss_coeff: float = 0.5,
        num_epochs: int = 4,
        target_kl: Optional[float] = None,
        norm_adv: bool = True,
        warmup_steps: int = 0,
        update_hidden_after_grad: bool = False,
        start_step: int = 0,
        # Task weight
        env_random_score: Optional[List[float]] = None,
        env_max_score: Optional[List[float]] = None,
        use_multitask_dynamic_weighting: bool = False,
        multitask_dynamic_weight_temperature: float = 10,
        multitask_static_weight: Optional[List[float]] = None,
        ):
    global_step_counter = [start_step, start_step]
    if max_steps_total > 0 and start_step > max_steps_total:
        print(f'Start step ({start_step}) is greater than max_steps_total ({max_steps_total}). Exiting.')
        return

    trainers = [
        train_single_env(
            global_step_counter = global_step_counter,
            model = model,
            env = env,
            env_labels = labels,
            obs_scale = obs_scale,
            rollout_length = rollout_length,
            reward_scale = reward_scale,
            reward_clip = reward_clip,
            discount = discount,
            gae_lambda = gae_lambda,
            clip_vf_loss = clip_vf_loss,
            entropy_loss_coeff = entropy_loss_coeff,
            vf_loss_coeff = vf_loss_coeff,
            num_epochs = num_epochs,
            target_kl = target_kl,
            norm_adv = norm_adv,
            warmup_steps = warmup_steps,
            update_hidden_after_grad = update_hidden_after_grad,
        )
        for env,labels in zip(envs, env_labels)
    ]

    multitask_weight = None
    if use_multitask_dynamic_weighting:
        assert multitask_static_weight is None
        assert env_random_score is not None
        assert env_max_score is not None
        assert len(env_random_score) == len(env_max_score)
        assert len(env_random_score) == len(envs)
        multitask_weight = MultitaskDynamicWeight(
            max_score = env_max_score,
            random_score = env_random_score,
            temperature = multitask_dynamic_weight_temperature,
        )
    elif multitask_static_weight is not None:
        assert len(multitask_static_weight) == len(envs)
        multitask_weight = MultitaskStaticWeight(
                multitask_static_weight
        )

    start_time = time.time()
    for _, losses in enumerate(zip(*trainers)):
        #env_steps = training_steps * rollout_length * sum(env.num_envs for env in envs)
        env_steps = global_step_counter[0]

        if max_steps > 0 and env_steps-start_step >= max_steps:
            print('Reached max steps')
            break
        if max_steps_total > 0 and env_steps >= max_steps_total:
            print('Reached total max steps')
            break

        if multitask_weight is not None:
            multitask_weight.step(
                [x['episode_rewards'] for x in losses]
            )
            all_losses = torch.stack([x['loss'] for x in losses])
            weight = torch.tensor(multitask_weight.weight, device=device)
            mean_loss = (all_losses * weight).sum()
            if wandb.run is not None:
                wandb.log({
                    f'multitask_dynamic_weight/{env_label}': w
                    for w, env_label in zip(weight, env_group_labels)
                }, step = global_step_counter[0])
        else:
            mean_loss = torch.stack([x['loss'] for x in losses]).mean()
        optimizer.zero_grad()
        mean_loss.backward()
        if max_grad_norm is not None:
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm) # type: ignore
        for p in model.parameters(): # XXX: Debugging code
            if p._grad is None:
                continue
            if p._grad.isnan().any():
                print('NaNs in gradients!')
                breakpoint()
        optimizer.step()

        if wandb.run is not None:
            for label,x in zip(env_group_labels, losses):
                data = {
                    f'loss/pi/{label}': x['loss_pi'].item(),
                    f'loss/v/{label}': x['loss_vf'].item(),
                    f'loss/entropy/{label}': x['loss_entropy'].item(),
                    f'loss/total/{label}': x['loss'].item(),
                    f'approx_kl/{label}': x['approx_kl'].item(),
                    f'state_value/{label}': x['log']['state_value'].mean().item(),
                    f'entropy/{label}': x['log']['entropy'].mean().item(),
                    #last_approx_kl=approx_kl.item(),
                    #'learning_rate': lr_scheduler.get_lr()[0],
                    'step': global_step_counter[0]-global_step_counter[1],
                    'step_total': global_step_counter[0],
                }
                if 'attention max' in x['log']:
                    for k,v in x['log']['attention max'].items():
                        data[f'attention max/{k}'] = v
                wandb.log(data, step = global_step_counter[0])

        yield {
            'step': global_step_counter[0],
        }

        # Update learning rate
        if lr_scheduler is not None:
            lr_scheduler.step()

        # Timing
        if env_steps > 0:
            elapsed_time = time.time() - start_time
            steps_per_sec = (env_steps - start_step) / elapsed_time
            if max_steps > 0:
                remaining_time = int((max_steps - env_steps) / steps_per_sec)
                remaining_hours = remaining_time // 3600
                remaining_minutes = (remaining_time % 3600) // 60
                remaining_seconds = (remaining_time % 3600) % 60
                print(f"Step {env_steps-start_step:,}/{max_steps:,} \t {int(steps_per_sec):,} SPS \t Remaining: {remaining_hours:02d}:{remaining_minutes:02d}:{remaining_seconds:02d}")
            else:
                elapsed_time = int(elapsed_time)
                elapsed_hours = elapsed_time // 3600
                elapsed_minutes = (elapsed_time % 3600) // 60
                elapsed_seconds = (elapsed_time % 3600) % 60
                print(f"Step {env_steps-start_step:,} \t {int(steps_per_sec):,} SPS \t Elapsed: {elapsed_hours:02d}:{elapsed_minutes:02d}:{elapsed_seconds:02d}")


if __name__ == '__main__':
    import argparse

    from big_rl.minigrid.arguments import init_parser_trainer, init_parser_model

    parser = argparse.ArgumentParser()

    parser.add_argument('--run-id', type=str, default=None,
                        help='Identifier for the current experiment. This value is used for setting the "{RUN_ID}" variable. If not specified, then either a slurm job ID is used, or the current date and time, depending on what is available. Note that the time-based ID has a resolution of 1 second, so if two runs are started within less than a second of each other, they may end up with the same ID.')

    parser.add_argument('--envs', type=str, default=['fetch-001'], nargs='*', help='Environments to train on')
    parser.add_argument('--num-envs', type=int, default=[16], nargs='*',
            help='Number of environments to train on. If a single number is specified, it will be used for all environments. If a list of numbers is specified, it must have the same length as --env.')
    parser.add_argument('--env-labels', type=str, default=None, nargs='*', help='')

    init_parser_trainer(parser)
    init_parser_model(parser)

    parser.add_argument('--starting-model', type=str, default=None,
                        help='Path to a model checkpoint to start training from.')
    parser.add_argument('--model-checkpoint', type=str, default=None,
                        help='Path to a model checkpoint to save the model to.')
    parser.add_argument('--checkpoint-interval', type=int, default=1000,
                        help='Number of training steps between checkpoints.')
    parser.add_argument('--ignore-checkpoint-optimizer', action='store_true',
                        help='If set, then the optimizer state is not loaded from the checkpoint.')
    parser.add_argument('--sync-vector-env', action='store_true',
                        help='If set, then the vectorized environments are synchronized. This is useful for debugging, but is likely slower, so it should not be used for training.')

    parser.add_argument('--slurm-split', action='store_true', help='Set this flag to let the script know it is running on a SLURM cluster with one job split across an array job. This ensures that the same checkpoint is used for each of these jobs.')
    parser.add_argument('--cuda', action='store_true', help='Use CUDA.')
    parser.add_argument('--wandb', action='store_true', help='Save results to W&B.')
    parser.add_argument('--wandb-id', type=str, default=None,
                        help='W&B run ID. Defaults to the run ID.')

    # Parse arguments
    args = parser.parse_args()

    # Post-process string arguments
    # Note: Only non-string arguments and args.run_id can be used until the post-processing is done.
    if args.run_id is None:
        args.run_id = generate_id(slurm_split = args.slurm_split)

    substitutions = dict(
        RUN_ID = args.run_id,
        SLURM_JOB_ID = os.environ.get('SLURM_JOB_ID', None),
        SLURM_ARRAY_JOB_ID = os.environ.get('SLURM_ARRAY_JOB_ID', None),
        SLURM_ARRAY_TASK_ID = os.environ.get('SLURM_ARRAY_TASK_ID', None),
        SLURM_TASK_ID = os.environ.get('SLURM_PROCID', None),
    )
    substitutions = {k:v.format(**substitutions) for k,v in substitutions.items() if v is not None} # Substitute values in `subsitutions` too in case they also have {} variables. None values are removed.
    for k,v in vars(args).items():
        if type(v) is str:
            v = v.format(**substitutions)
            setattr(args, k, v)

    print(substitutions)
    print('-'*80)
    print(f'Run ID: {args.run_id}')
    print(f'W&B ID: {args.wandb_id}')
    print('-'*80)

    # Initialize W&B
    if args.wandb:
        if args.wandb_id is not None:
            wandb.init(project='ppo-multitask-minigrid', id=args.wandb_id, resume='allow')
        elif args.model_checkpoint is not None: # XXX: Questionable decision. Maybe it should be explicitly specified as a CLI argument if we want to use the same W&B ID. This is causing more problems than it solves.
            wandb_id = os.path.basename(args.model_checkpoint).split('.')[0]
            wandb.init(project='ppo-multitask-minigrid', id=wandb_id, resume='allow')
        else:
            wandb.init(project='ppo-multitask-minigrid')
        wandb.config.update(args)

    ENV_CONFIG_PRESETS = env_config_presets()
    env_configs = [
        [ENV_CONFIG_PRESETS[e] for _ in range(n)]
        for e,n in zip(args.envs, args.num_envs)
    ]
    VectorEnv = gymnasium.vector.SyncVectorEnv if args.sync_vector_env else gymnasium.vector.AsyncVectorEnv
    envs = [
        VectorEnv([lambda conf=conf: make_env(**conf) for conf in env_config]) # type: ignore (Why is `make_env` missing an argument?)
        for env_config in env_configs
    ]

    if args.cuda and torch.cuda.is_available():
        print('Using CUDA')
        device = torch.device('cuda')
    else:
        print('Using CPU')
        device = torch.device('cpu')

    # Initialize model
    model = init_model(
            observation_space = merge_space(*[env.single_observation_space for env in envs]),
            action_space = envs[0].single_action_space, # Assume the same action space for all environments
            model_type = args.model_type,
            recurrence_type = args.recurrence_type,
            architecture = args.architecture,
            ff_size = args.ff_size,
            hidden_size = args.hidden_size,
            device = device,
    )
    model.to(device)

    # Initialize optimizer
    if args.optimizer == 'Adam':
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    elif args.optimizer == 'RMSprop':
        optimizer = torch.optim.RMSprop(model.parameters(), lr=args.lr)
    elif args.optimizer == 'SGD':
        optimizer = torch.optim.SGD(model.parameters(), lr=args.lr)
    else:
        raise ValueError(f'Unknown optimizer: {args.optimizer}')

    # Initialize learning rate scheduler
    lr_scheduler = None # TODO

    # Load checkpoint
    start_step = 0
    checkpoint = None

    if args.model_checkpoint is not None and os.path.exists(args.model_checkpoint) and os.stat(args.model_checkpoint).st_size > 0:
        assert not os.path.isdir(args.model_checkpoint), 'Model checkpoint must be a file, not a directory'
        # The checkpoint exists, which means the experiment already started. Resume the experiment instead of restarting it.
        # If the checkpoint file is empty, it means we just created the file and the experiment hasn't started yet.
        checkpoint = torch.load(args.model_checkpoint, map_location=device)
        print(f'Experiment already started. Loading checkpoint from {args.model_checkpoint}')
    elif args.starting_model is not None:
        checkpoint = torch.load(args.starting_model, map_location=device)
        print(f'Loading starting model from {args.starting_model}')

    if checkpoint is not None:
        model.load_state_dict(checkpoint['model'], strict=False)
        if 'optimizer' in checkpoint and not args.ignore_checkpoint_optimizer:
            optimizer.load_state_dict(checkpoint['optimizer'])
        if lr_scheduler is not None and 'lr_scheduler' in checkpoint:
            lr_scheduler.load_state_dict(checkpoint['lr_scheduler'])
        start_step = checkpoint.get('step', 0)
        print(f'Loaded checkpoint from {args.starting_model}')

    # Initialize trainer
    trainer = train(
            model = model,
            envs = envs, # type: ignore (??? AsyncVectorEnv is not a subtype of VectorEnv ???)
            #env_labels = [['doot']*len(envs)], # TODO: Make this configurable
            #env_labels = [[e]*n for e,n in zip(args.envs, args.num_envs)],
            env_labels = [[e]*n for e,n in zip(args.envs, args.num_envs)],
            env_group_labels = args.envs,
            optimizer = optimizer,
            lr_scheduler = lr_scheduler,
            max_steps = args.max_steps,
            max_steps_total = args.max_steps_total,
            rollout_length = args.rollout_length,
            obs_scale = {'obs (image)': 1.0/255.0},
            reward_clip = args.reward_clip,
            reward_scale = args.reward_scale,
            discount = args.discount,
            gae_lambda = args.gae_lambda,
            norm_adv = args.norm_adv,
            clip_vf_loss = args.clip_vf_loss,
            vf_loss_coeff = args.vf_loss_coeff,
            entropy_loss_coeff = args.entropy_loss_coeff,
            target_kl = args.target_kl,
            num_epochs = args.num_epochs,
            max_grad_norm = args.max_grad_norm,
            warmup_steps = args.warmup_steps,
            update_hidden_after_grad = args.update_hidden_after_grad,
            start_step = start_step,
            env_random_score = args.random_score,
            env_max_score = args.max_score,
            use_multitask_dynamic_weighting = args.multitask_dynamic_weight,
            multitask_dynamic_weight_temperature = args.multitask_dynamic_weight_temperature,
            multitask_static_weight = args.multitask_static_weight,
    )

    # Run training loop
    if args.model_checkpoint is not None:
        os.makedirs(os.path.dirname(args.model_checkpoint), exist_ok=True)
        if not args.model_checkpoint.endswith('.pt'):
            # If the path is a directory, generate a unique filename
            raise NotImplementedError()
        while True:
            x = None
            for _,x in zip(range(args.checkpoint_interval), trainer):
                pass
            # If x is None, it means no training has occured
            if x is None:
                break
            # Only save the model if training has occured
            torch_save({
                'model': model.state_dict(),
                'optimizer': optimizer.state_dict(),
                'step': x['step'],
            }, args.model_checkpoint)
            print(f'Saved checkpoint to {os.path.abspath(args.model_checkpoint)}')
    else:
        x = None
        try:
            for x in trainer:
                pass
        except KeyboardInterrupt:
            print('Interrupted')
            pass
        # Sometimes, we run an experiment without intending to save the model, but then change our mind later.
        if x is not None:
            print('Saving model')
            tmp_checkpoint = f'./temp-checkpoint.pt'
            torch_save({
                'model': model.state_dict(),
                'optimizer': optimizer.state_dict(),
                'step': x['step'],
            }, tmp_checkpoint)
            print(f'Saved temporary checkpoint to {os.path.abspath(tmp_checkpoint)}')
