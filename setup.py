from setuptools import setup, find_packages

setup(name='big_rl',
    version='0.0.1',
    install_requires=[
        'gymnasium>=0.27.0',
        'torch>=1.11.0',
        'torchtyping',
        'matplotlib',
        'tqdm',
        'wandb',
        'scikit-learn',
        'tabulate>=0.9.0',
        'tensordict>=0.1.0',
        'h5py',
        
        # Minigrid
        'minigrid',
        'opencv-python',
        'permutation',
        'scipy',
        'font-roboto==0.0.1',
        'fonts==0.0.3',

        # Mujoco
        'beautifulsoup4', # Needed for manipulating MJCF files
        'lxml',

        # Atari (Not yet compatible with Gymnasium)
        #'gym[atari,accept-rom-license]',

        # Dev stuff
        'pytest',
        'flake8',
    ],
    packages=find_packages(),
    package_dir={'': '.'},
    package_data={
        #'big_rl': ['big_rl/mujoco/envs/assets/*.xml']
        'big_rl.mujoco.envs.assets': ['*.xml']
        #'big_rl': ['*.xml']
    }
)
