import itertools

import torch
from minigrid.core.constants import COLOR_NAMES

from big_rl.model.model import ModularPolicy2, ModularPolicy4, ModularPolicy5, ModularPolicy5LSTM, ModularPolicy7
from big_rl.model.modular_policy_8 import ModularPolicy8
from big_rl.model.baseline import BaselineModel
from big_rl.utils import ExperimentConfigs


def init_model(observation_space, action_space,
        model_type,
        recurrence_type,
        num_recurrence_blocks=3,
        architecture=[3,3],
        ff_size=[1024],
        hidden_size=None, # For LSTM model only
        device=torch.device('cpu')):
    observation_space = observation_space # Unused variable
    inputs = {
        'obs (image)': {
            'type': 'ImageInput56',
            'config': {
                'in_channels': observation_space['obs (image)'].shape[0]
            },
        },
        'reward': {
            'type': 'ScalarInput',
        },
        'action': {
            'type': 'DiscreteInput',
            'config': {
                'input_size': action_space.n
            },
        },
    }
    # XXX: The membership test behaviour changes between gym and gymnasium. If any libraries are updated, make sure that this still works.
    if 'obs (reward_permutation)' in list(observation_space.keys()):
        inputs['obs (reward_permutation)'] = {
            'type': 'LinearInput',
            'config': {
                'input_size': observation_space['obs (reward_permutation)'].shape[0]
            }
        }
    if 'obs (shaped_reward)' in list(observation_space.keys()):
        inputs['obs (shaped_reward)'] = {
            'type': 'ScalarInput',
            'input_mapping': ['obs (shaped_reward)', 'obs (pseudo_reward)'],
        }
    if 'action_map' in list(observation_space.keys()):
        inputs['action_map'] = {
            'type': 'MatrixInput',
            'config': {
                'input_size': list(observation_space['action_map'].shape),
                'num_heads': 8,
            }
        }
    outputs = {
        'value': {
            'type': 'LinearOutput',
            'config': {
                'output_size': 1,
            }
        },
        'action': {
            'type': 'LinearOutput',
            'config': {
                'output_size': action_space.n,
            }
        },
    }
    common_model_params = {
        'inputs': inputs,
        'outputs': outputs,
        'input_size': 512,
        'key_size': 512,
        'value_size': 512,
        'num_heads': 8,
        'ff_size': ff_size[0] if len(ff_size) == 1 else ff_size,
        'recurrence_type': recurrence_type,
    }
    if model_type == 'ModularPolicy2':
        return ModularPolicy2(
                **common_model_params,
                num_blocks=num_recurrence_blocks,
        ).to(device)
    elif model_type == 'ModularPolicy4':
        assert architecture is not None
        return ModularPolicy4(
                **common_model_params,
                architecture=architecture,
        ).to(device)
    elif model_type == 'ModularPolicy5':
        assert architecture is not None
        return ModularPolicy5(
                **common_model_params,
                architecture=architecture,
        ).to(device)
    elif model_type == 'ModularPolicy5LSTM':
        assert architecture is not None
        for k in ['reward', 'obs (shaped_reward)']:
            if k not in inputs:
                continue
            inputs[k]['config'] = {
                    **inputs[k].get('config', {}),
                    'value_size': 1,
            }
        return ModularPolicy5LSTM(
                inputs=inputs,
                outputs=outputs,
                value_size=common_model_params['value_size'],
                hidden_size=hidden_size,
        ).to(device)
    elif model_type == 'ModularPolicy7':
        assert architecture is not None
        return ModularPolicy7(
                **common_model_params,
                architecture=architecture,
        ).to(device)
    elif model_type == 'ModularPolicy8':
        recurrence_kwargs = {
            'ff_size': common_model_params.pop('ff_size'),
        }
        if architecture is not None:
            recurrence_kwargs['architecture'] = architecture
        return ModularPolicy8(
                **common_model_params,
                recurrence_kwargs=recurrence_kwargs,
        ).to(device)
    elif model_type == 'Baseline':
        # Similar to ModularPolicy5LSTM setup
        assert architecture is not None
        for k in ['reward', 'obs (shaped_reward)']:
            if k not in inputs:
                continue
            inputs[k]['config'] = {
                    **inputs[k].get('config', {}),
                    'value_size': 1,
            }
        return BaselineModel(
                inputs=inputs,
                outputs=outputs,
                value_size=common_model_params['value_size'],
                architecture=architecture,
        ).to(device)
    raise NotImplementedError()


def env_config_presets():
    config = ExperimentConfigs()

    def init_fetch():
        config.add('fetch-debug', {
            'env_name': 'MiniGrid-MultiRoom-v1',
            'minigrid_config': {},
            'meta_config': {
                'episode_stack': 1,
                'dict_obs': True,
                'randomize': False,
            },
            'config': {
                'num_trials': 1,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 5,
                'max_room_size': 5,
                'door_prob': 0.5,
                'max_steps_multiplier': 5,
                'fetch_config': {
                    'num_objs': 2,
                    'num_obj_types': 1,
                    'num_obj_colors': 2,
                    'prob': 1.0, # 0.0 chance of flipping the reward
                },
                #'task_randomization_prob': 0.02, # 86% chance of happening at least once, with a 50% change of the randomized task being unchanged.
            }
        })
        config.add('fetch-001', {
            'env_name': 'MiniGrid-MultiRoom-v1',
            'minigrid_config': {},
            'meta_config': {
                'episode_stack': 1,
                'dict_obs': True,
                'randomize': False,
            },
            'config': {
                'num_trials': 100,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 5,
                'max_room_size': 5,
                'door_prob': 0.5,
                'max_steps_multiplier': 5,
                'fetch_config': {
                    'num_objs': 2,
                    'num_obj_types': 1,
                    'num_obj_colors': 2,
                    'prob': 1.0, # 0.0 chance of flipping the reward
                },
            }
        })
        config.add_change('fetch-002', {
            'config': {
                'num_trials': 100,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 8,
                'max_room_size': 16,
                'fetch_config': {
                    'num_objs': 2,
                    'num_obj_types': 2,
                    'num_obj_colors': 6,
                },
            }
        })
        config.add_change('fetch-002-shaped', {
            'config': {
                'shaped_reward_config': {
                    'type': 'inverse distance',
                },
            }
        })
        config.add_change('fetch-002-shaped-adjacent', {
            'config': {
                'shaped_reward_config': {
                    'type': 'adjacent to subtask',
                },
            }
        })

        # Noisy shaped rewards
        config.add('fetch-002-shaped-noisy-debug', {
            'config': {
                'shaped_reward_config': {
                    'type': 'adjacent to subtask',
                    'noise': ('stop', 500, 'steps'),
                },
            }
        }, inherit='fetch-002')

        # Skipping 003 to match up with the delayed task numbering
        config.add('fetch-004', {
            'config': {
                'min_room_size': 4,
                'max_room_size': 6,
                'reward_type': 'standard',
            }
        }, inherit='fetch-002')
        config.add_change('fetch-004-pbrs', {
            'config': {
                'reward_type': 'pbrs',
                'pbrs_scale': 0.1,
                'pbrs_discount': 0.99,
            }
        })
        config.add('fetch-004-shaped', {
            'config': {
                'shaped_reward_config': {
                    'type': 'inverse distance',
                },
            }
        }, inherit='fetch-004')

        # Increase map size from 4-6 to 5-8
        config.add('fetch-004-bigger', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch-004')
        config.add('fetch-004-bigger-pbrs', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch-004-pbrs')
        config.add('fetch-004-bigger-shaped', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch-004-shaped')

        # Remove reward signal, keep shaped reward, but cut off shaped reward after some number of steps
        for cutoff in [1000, 100, 50, 0]:
            config.add(f'fetch-004-stop_{cutoff}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('stop', cutoff, 'trials'),
                    },
                }
            }, inherit='fetch-004')
            config.add(f'fetch-004-stop_{cutoff}_trials-green_key', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'fetch_config': {
                        'num_objs': 2,
                        'num_obj_types': 1,
                        'num_obj_colors': 2,
                        'fixed_target': ('key', 'green'),
                    },
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('stop', cutoff, 'trials'),
                    },
                }
            }, inherit='fetch-004')
            config.add(f'fetch-004-stop_{cutoff}_trials-blue_key', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'fetch_config': {
                        'num_objs': 2,
                        'num_obj_types': 1,
                        'num_obj_colors': 2,
                        'fixed_target': ('key', 'blue'),
                    },
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('stop', cutoff, 'trials'),
                    },
                }
            }, inherit='fetch-004')
        for x in range(2,51):
            config.add(f'fetch-004-zero_{x}_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('zero', (x,x), 'cycle_trials'),
                    },
                }
            }, inherit='fetch-004')
        config.add(f'fetch-004-zero_dynamic', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'shaped_reward_config': {
                    'type': 'subtask',
                    'noise': ('dynamic_zero', 10, (0.8, 0.1)),
                },
            }
        }, inherit='fetch-004')
        config.add(f'fetch-004-stop_dynamic', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'shaped_reward_config': {
                    'type': 'subtask',
                    'noise': ('dynamic_zero', 10, (0.8, -float('inf'))), # Never resume after the reward is stopped.
                },
            }
        }, inherit='fetch-004')

        # 
        config.add(f'fetch-004-alternating', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'fetch_config': {
                    'cycle_targets': True
                },
                'shaped_reward_config': {
                    'type': 'subtask',
                },
            }
        }, inherit='fetch-004')

        # 005: Same as above, but with bigger rooms
        for cutoff in [500, 200, 100, 50, 20, 1]:
            config.add(f'fetch-005-stop_{cutoff}', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('stop', cutoff, 'steps'),
                    },
                }
            }, inherit='fetch-004')
            for delay in [1]:
                config.add(f'fetch-005-stop_{cutoff}-delay_{delay}', {
                    'meta_config': {
                        'include_reward': False,
                    },
                    'config': {
                        'min_room_size': 5,
                        'max_room_size': 12,
                        'shaped_reward_config': {
                            'type': 'subtask',
                            'noise': ('stop', cutoff, 'steps'),
                            'delay': ('fixed', delay)
                        },
                    }
                }, inherit='fetch-004')
            for delay in [(1,2)]:
                config.add(f'fetch-005-stop_{cutoff}-delay_{delay[0]}_{delay[1]}', {
                    'meta_config': {
                        'include_reward': False,
                    },
                    'config': {
                        'min_room_size': 5,
                        'max_room_size': 12,
                        'shaped_reward_config': {
                            'type': 'subtask',
                            'noise': ('stop', cutoff, 'steps'),
                            'delay': ('random', delay[0], delay[1])
                        },
                    }
                }, inherit='fetch-004')
        for cutoff in [100, 50, 0]:
            config.add(f'fetch-005-stop_{cutoff}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('stop', cutoff, 'trials'),
                    },
                }
            }, inherit='fetch-004')
        for x in range(1,10):
            config.add(f'fetch-005-zero_1_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('zero', (1,x), 'cycle_trials'),
                    },
                }
            }, inherit='fetch-004')
        for x in range(2,51):
            config.add(f'fetch-005-zero_{x}_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('zero', (x,x), 'cycle_trials'),
                    },
                }
            }, inherit='fetch-004')
        for x in [70]:
            config.add(f'fetch-005-zero_30_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'noise': ('zero', (30,x), 'cycle_trials'),
                    },
                }
            }, inherit='fetch-004')
        config.add(f'fetch-005-zero_dynamic', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch-004-zero_dynamic')
        config.add(f'fetch-005-stop_dynamic', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch-004-stop_dynamic')
        for a,b in [(0,5), (1,5)]:
            config.add(f'fetch-005-delay_{a}_{b}', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'delay': ('random', (a, b), 'replace')
                    },
                }
            }, inherit='fetch-004')
            config.add(f'fetch-005-stop_dynamic-delay_{a}_{b}', {
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'delay': ('random', (a, b), 'replace')
                    },
                }
            }, inherit='fetch-004-stop_dynamic')
        for a,b in [(0,5), (1,5), (1,10), (1,20), (10,20), (10,30)]:
            config.add(f'fetch-005-delayed_start_{a}_{b}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'delayed_start': ('random', (a, b), 'trials')
                    },
                }
            }, inherit='fetch-004')
        for n in [10,20,50,100]:
            config.add(f'fetch-005-delayed_start_{n}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'shaped_reward_config': {
                        'type': 'subtask',
                        'delayed_start': ('fixed', n, 'trials')
                    },
                }
            }, inherit='fetch-004')
        config.add(f'fetch-005-randomized_task', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
                'task_randomization_prob': 0.02,
                'shaped_reward_config': {
                    'type': 'subtask',
                },
            }
        }, inherit='fetch-004')

        config.add(f'fetch-005-alternating', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
                'fetch_config': {
                    'cycle_targets': True
                },
                'shaped_reward_config': {
                    'type': 'subtask',
                },
            }
        }, inherit='fetch-004')


    def init_delayed():
        config.add('delayed-001', {
            'env_name': 'MiniGrid-Delayed-Reward-v0',
            'minigrid_config': {},
            'meta_config': {
                'episode_stack': 1,
                'dict_obs': True,
                'randomize': False,
            },
            'config': {
                'num_trials': 100,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 5,
                'max_room_size': 6,
                'door_prob': 0.5,
                'fetch_config': {
                    'num_objs': 2,
                    'num_obj_colors': 6,
                    'prob': 1.0, # 0.0 chance of flipping the reward
                },
            }
        })

        config.add_change('delayed-002', {
            # Looks like I forgot to make changes?
        })

        config.add_change('delayed-003', {
            'config': {
                'min_room_size': 8,
                'max_room_size': 16,
            }
        })
        config.add_change('delayed-003-shaped', {
            'config': {
                'shaped_reward_config': {
                    'type': 'inverse distance',
                },
            }
        })
        config.add_change('delayed-003-shaped-adjacent', {
            'config': {
                'shaped_reward_config': {
                    'type': 'adjacent to subtask',
                },
            }
        })

        # Noisy shaped rewards
        for cutoff in [500, 200, 100, 1, 0]:
            config.add(f'delayed-003-shaped_adjacent-stop_noise_{cutoff}', {
                'config': {
                    'shaped_reward_config': {
                        'type': 'adjacent to subtask',
                        'noise': ('stop', cutoff, 'steps'),
                    },
                }
            }, inherit='delayed-003')


    def init_fetch2():
        config.add('fetch2-debug', {
            'env_name': 'MiniGrid-MultiRoom-v2',
            'minigrid_config': {},
            'meta_config': {
                'episode_stack': 1,
                'dict_obs': True,
                'randomize': False,
            },
            'config': {
                'num_trials': 1,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 5,
                'max_room_size': 5,
                'door_prob': 0.5,
                'max_steps_multiplier': 5,
                'num_objs': 2,
                'num_obj_types': 1,
                'num_obj_colors': 2,
                'task_config': {
                    'task': 'fetch',
                    'args': {
                        'reward_correct': 1,
                        'reward_incorrect': -1,
                        'reward_flip_prob': 0.0,
                    }
                }
            }
        })
        config.add('fetch2-001', {
            'env_name': 'MiniGrid-MultiRoom-v2',
            'minigrid_config': {},
            'meta_config': {
                'episode_stack': 1,
                'dict_obs': True,
                'randomize': False,
            },
            'config': {
                'num_trials': 100,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 5,
                'max_room_size': 5,
                'door_prob': 0.5,
                'max_steps_multiplier': 5,
                'num_objs': 2,
                'num_obj_types': 1,
                'num_obj_colors': 2,
                'task_config': {
                    'task': 'fetch',
                    'args': {
                        'reward_correct': 1,
                        'reward_incorrect': -1,
                        'reward_flip_prob': 0,
                    }
                }
            }
        })
        config.add_change('fetch2-002', {
            'config': {
                'num_trials': 100,
                'min_num_rooms': 1,
                'max_num_rooms': 1,
                'min_room_size': 8,
                'max_room_size': 16,
                'num_objs': 2,
                'num_obj_types': 2,
                'num_obj_colors': 6,
            }
        })
        config.add_change('fetch2-002-shaped', {
            'config': {
                'task_config': {
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'inverse distance',
                        },
                    }
                }
            }
        })
        config.add_change('fetch2-002-shaped-adjacent', {
            'config': {
                'task_config': {
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'adjacent to subtask',
                        },
                    }
                }
            }
        })

        # Noisy shaped rewards
        config.add('fetch2-002-shaped-noisy-debug', {
            'config': {
                'task_config': {
                    'pseudo_reward_config': {
                        'noise': ('stop', 500, 'steps'),
                    },
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'adjacent to subtask',
                        },
                    }
                }
            }
        }, inherit='fetch2-002')

        # Skipping 003 to match up with the delayed task numbering
        config.add('fetch2-004', {
            'config': {
                'min_room_size': 4,
                'max_room_size': 6,
                'task_config': {
                    'args': {
                        'reward_type': 'standard',
                    }
                }
            }
        }, inherit='fetch2-002')
        config.add_change('fetch2-004-pbrs', {
            'config': {
                'task_config': {
                    'args': {
                        'reward_type': 'pbrs',
                        'pbrs_scale': 0.1,
                        'pbrs_discount': 0.99,
                    }
                }
            }
        })
        config.add('fetch2-004-shaped', {
            'config': {
                'task_config': {
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'inverse distance',
                        },
                    }
                }
            }
        }, inherit='fetch2-004')

        # Increase map size from 4-6 to 5-8
        config.add('fetch2-004-bigger', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch2-004')
        config.add('fetch2-004-bigger-pbrs', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch2-004-pbrs')
        config.add('fetch2-004-bigger-shaped', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch2-004-shaped')

        # Remove reward signal, keep shaped reward, but cut off shaped reward after some number of steps
        for cutoff in [1000, 100, 50, 0]:
            config.add(f'fetch2-004-stop_{cutoff}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'pseudo_reward_config': {
                        'noise': ('stop', cutoff, 'trials'),
                    },
                    'task_config': {
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    }
                }
            }, inherit='fetch2-004')
            config.add(f'fetch2-004-stop_{cutoff}_trials-green_key', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'num_objs': 2,
                    'num_obj_types': 1,
                    'num_obj_colors': 2,
                    'pseudo_reward_config': {
                        'noise': ('stop', cutoff, 'trials'),
                    },
                    'task_config': {
                        'args': {
                            'fixed_target': ('key', 'green'),
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    }
                }
            }, inherit='fetch2-004')
            config.add(f'fetch2-004-stop_{cutoff}_trials-blue_key', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'num_objs': 2,
                    'num_obj_types': 1,
                    'num_obj_colors': 2,
                    'pseudo_reward_config': {
                        'noise': ('stop', cutoff, 'trials'),
                    },
                    'task_config': {
                        'args': {
                            'fixed_target': ('key', 'blue'),
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    }
                }
            }, inherit='fetch2-004')

            # Same as above, but the target object can be paired with any other object
            for obj_color, obj_type in itertools.product(COLOR_NAMES, ['ball', 'key']):
                config.add(f'fetch2-004-stop_{cutoff}_trials-{obj_color}_{obj_type}-2', {
                    'meta_config': {
                        'include_reward': False,
                    },
                    'config': {
                        'num_objs': 2,
                        'num_obj_types': 2,
                        'num_obj_colors': 6,
                        'required_objs': [(obj_type, obj_color)],
                        'pseudo_reward_config': {
                            'noise': ('stop', cutoff, 'trials'),
                        },
                        'task_config': {
                            'args': {
                                'fixed_target': (obj_type, obj_color),
                                'pseudo_reward_config': {
                                    'type': 'subtask',
                                },
                            }
                        }
                    }
                }, inherit='fetch2-004')
        for x in range(2,51):
            config.add(f'fetch2-004-zero_{x}_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'pseudo_reward_config': {
                        'noise': ('zero', (x,x), 'cycle_trials'),
                    },
                    'task_config': {
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        config.add(f'fetch2-004-zero_dynamic', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'pseudo_reward_config': {
                    'noise': ('dynamic_zero', 10, (0.8, 0.1)),
                },
                'task_config': {
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'subtask',
                        },
                    }
                },
            }
        }, inherit='fetch2-004')
        config.add(f'fetch2-004-stop_dynamic', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'pseudo_reward_config': {
                    'noise': ('dynamic_zero', 10, (0.8, -float('inf'))), # Never resume after the reward is stopped.
                },
                'task_config': {
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'subtask',
                        },
                    }
                },
            }
        }, inherit='fetch2-004')

         
        config.add(f'fetch2-004-alternating', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'task_config': {
                    'task': 'fetch',
                    'args': {
                        'cycle_targets': True,
                        'pseudo_reward_config': {
                            'type': 'subtask',
                        },
                    }
                },
            }
        }, inherit='fetch2-004')

        # 005: Same as above, but with bigger rooms
        for cutoff in [500, 200, 100, 50, 20, 1]:
            config.add(f'fetch2-005-stop_{cutoff}', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'noise': ('stop', cutoff, 'steps'),
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
            for delay in [1]:
                config.add(f'fetch2-005-stop_{cutoff}-delay_{delay}', {
                    'meta_config': {
                        'include_reward': False,
                    },
                    'config': {
                        'min_room_size': 5,
                        'max_room_size': 12,
                        'pseudo_reward_config': {
                            'noise': ('stop', cutoff, 'steps'),
                            'delay': ('fixed', delay)
                        },
                        'task_config': {
                            'task': 'fetch',
                            'args': {
                                'pseudo_reward_config': {
                                    'type': 'subtask',
                                },
                            }
                        },
                    }
                }, inherit='fetch2-004')
            for delay in [(1,2)]:
                config.add(f'fetch2-005-stop_{cutoff}-delay_{delay[0]}_{delay[1]}', {
                    'meta_config': {
                        'include_reward': False,
                    },
                    'config': {
                        'min_room_size': 5,
                        'max_room_size': 12,
                        'pseudo_reward_config': {
                            'noise': ('stop', cutoff, 'steps'),
                            'delay': ('random', delay[0], delay[1])
                        },
                        'tasks': {
                            'task': 'fetch',
                            'args': {
                                'pseudo_reward_config': {
                                    'type': 'subtask',
                                },
                            }
                        },
                    }
                }, inherit='fetch2-004')
        for cutoff in [100, 50, 0]:
            config.add(f'fetch2-005-stop_{cutoff}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'noise': ('stop', cutoff, 'trials'),
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        for x in range(1,10):
            config.add(f'fetch2-005-zero_1_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'noise': ('zero', (1,x), 'cycle_trials'),
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        for x in range(2,51):
            config.add(f'fetch2-005-zero_{x}_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'noise': ('zero', (x,x), 'cycle_trials'),
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        for x in [70]:
            config.add(f'fetch2-005-zero_30_{x}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'noise': ('zero', (30,x), 'cycle_trials'),
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        config.add(f'fetch2-005-zero_dynamic', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch2-004-zero_dynamic')
        config.add(f'fetch2-005-stop_dynamic', {
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
            }
        }, inherit='fetch2-004-stop_dynamic')
        for a,b in [(0,5), (1,5)]:
            config.add(f'fetch2-005-delay_{a}_{b}', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'delay': ('random', (a, b), 'replace')
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
            config.add(f'fetch2-005-stop_dynamic-delay_{a}_{b}', {
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'delay': ('random', (a, b), 'replace')
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004-stop_dynamic')
        for a,b in [(0,5), (1,5), (1,10), (1,20), (10,20), (10,30)]:
            config.add(f'fetch2-005-delayed_start_{a}_{b}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'delayed_start': ('random', (a, b), 'trials')
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        for n in [10,20,50,100]:
            config.add(f'fetch2-005-delayed_start_{n}_trials', {
                'meta_config': {
                    'include_reward': False,
                },
                'config': {
                    'min_room_size': 5,
                    'max_room_size': 12,
                    'pseudo_reward_config': {
                        'delayed_start': ('fixed', n, 'trials')
                    },
                    'task_config': {
                        'task': 'fetch',
                        'args': {
                            'pseudo_reward_config': {
                                'type': 'subtask',
                            },
                        }
                    },
                }
            }, inherit='fetch2-004')
        config.add(f'fetch2-005-randomized_task', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
                'task_config': {
                    'task': 'fetch',
                    'args': {
                        'pseudo_reward_config': {
                            'type': 'subtask',
                        },
                    },
                    'wrappers': [{
                        'type': 'random_reset',
                        'args': {
                            'prob': 0.02,
                        },
                    }]
                },
            }
        }, inherit='fetch2-004')

        config.add(f'fetch2-005-alternating', {
            'meta_config': {
                'include_reward': False,
            },
            'config': {
                'min_room_size': 5,
                'max_room_size': 12,
                'task_config': {
                    'task': 'fetch',
                    'args': {
                        'cycle_targets': True,
                        'pseudo_reward_config': {
                            'type': 'subtask',
                        },
                    },
                },
            }
        }, inherit='fetch2-004')

    init_fetch()
    init_delayed()
    init_fetch2()

    return config

