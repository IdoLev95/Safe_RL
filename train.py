import os
import numpy as np
import random
import torch
import shutil

from common.past.utils import *
#from common.past.arguments import get_args
from common.ours.arguments import get_args

# SARSA agents
from agents.past.sarsa_agent import SarsaAgent
from agents.past.safe_sarsa_agent import SafeSarsaAgent
from agents.past.lyp_sarsa_agent import LypSarsaAgent
from agents.ours.hrl_sarsa_agent import HRL_Discrete_Goal_SarsaAgent

"""
# A2C based agents
from agents.a2c_agent import A2CAgent
from agents.lyp_a2c_agent import LyapunovA2CAgent
from agents.safe_a2c_v2_agent import SafeA2CProjectionAgent

# PPO based agents
from agents.ppo import PPOAgent
from agents.safe_ppo import SafePPOAgent
from agents.lyp_ppo import LyapunovPPOAgent
# target based agents
from agents.target_agents.target_bvf_ppo import TargetBVFPPOAgent
from agents.target_agents.target_lyp_ppo import TargetLypPPOAgent
"""


# get the args from argparse
args = get_args()
# dump the args
log(args)


# initialize a random seed for the experiment
seed = np.random.randint(1,1000)
args.seed = seed
random.seed(args.seed)
torch.manual_seed(args.seed)
torch.cuda.manual_seed_all(args.seed)
np.random.seed(args.seed)

# pytorch multiprocessing flag
torch.set_num_threads(1)

# check the device here
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# get the filename
name = get_filename(args)
args.out = os.path.join(args.out, args.env_name, args.agent, name)
tb_log_dir = os.path.join(args.log_dir, args.env_name, args.agent, name, 'tb_logs')
if args.reset_dir:
    shutil.rmtree(args.out, ignore_errors=True) #delete the results dir
    shutil.rmtree(tb_log_dir, ignore_errors=True) #delete the tb dir

os.makedirs(args.out, exist_ok=True)
os.makedirs(tb_log_dir, exist_ok=True)

# don't use tb on cluster
tb_writer = None

# print the dir in the beginning
print("Log dir", tb_log_dir)
print("Out dir", args.out)


agent = None

# create the env here
env = create_env(args)

"""
# create the agent here
# PPO based agents
if args.agent == "ppo":
    agent = PPOAgent(args, env)
elif args.agent == "bvf-ppo":
    if args.target:
        agent = TargetBVFPPOAgent(args, env)
    else:
        agent = SafePPOAgent(args, env, writer=tb_writer)
elif args.agent == "lyp-ppo":
    if args.target:
        agent = TargetLypPPOAgent(args, env)
    else:
        agent = LyapunovPPOAgent(args, env)
# A2C based agents
elif args.agent == "a2c":
    agent = A2CAgent(args, env, writer=tb_writer)
elif args.agent == "safe-a2c":
    agent = SafeA2CProjectionAgent(args, env, writer=tb_writer)
elif args.agent == "lyp-a2c":
    agent = LyapunovA2CAgent(args, env, writer=tb_writer)
"""

from multiprocessing import freeze_support, set_start_method



freeze_support()
#  SARSA based agent
if args.agent == "sarsa":
    agent = SarsaAgent(args, env, writer=tb_writer, save_dir=args.save_dir, exp_no=args.exp_no)
elif args.agent == "bvf-sarsa":
    agent = SafeSarsaAgent(args, env, writer=tb_writer, save_dir=args.save_dir, exp_no=args.exp_no)
elif args.agent == "lyp-sarsa":
    agent = LypSarsaAgent(args, env, writer=tb_writer)
elif args.agent == "hrl-sarsa":
    agent = HRL_Discrete_Goal_SarsaAgent(args, env, save_dir=args.save_dir, exp_no=args.exp_no)
else:
    raise Exception("Not implemented yet")


print("experiment_numer " + str(args.exp_no))
# start the run process here

agent.run()

# notify when finished
print("finished!")
