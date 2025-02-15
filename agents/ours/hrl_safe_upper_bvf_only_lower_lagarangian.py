import math
import numpy as np
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import random
import gym
import copy
import numpy as np


from common.past.utils import *
from common.ours.grid.utils import Goal_Space

from common.past.multiprocessing_envs import SubprocVecEnv
from torchvision.transforms import ToTensor

from models.ours.grid_model import OneHotDQN, OneHotValueNetwork, OneHotCostAllocator

from common.past.schedules import LinearSchedule, ExponentialSchedule

class HRL_Discrete_Safe_Upper_BVF_Only_lower_Lagrangian(object):

    def __init__(self,
                 args,
                 env,
                 goal_space=None,
                 writer = None,
                 save_dir=None,
                 exp_no=None,
                 #lam= 0.5,
                 lam= 1,
                 #lam=1,
                 ):
        """
        init the agent here
        """

        self.cost_estimate_L = []
        self.action_mask_L = []
        self.cost_L = []
        self.cost_U = []

        self.f_value_l = []
        self.f_q_value_l = []

        self.r_value_u = []
        self.f_q_value_u = []

        self.value_G1 = []
        self.value_G2 = []
        self.value_G3 = []

        self.adj_key1 = []
        self.adj_key2 = []
        self.adj_key3 = []


        self.lam = lam
        self.exp_no = exp_no
        self.save_dir = save_dir
        args.num_envs = 1
        if goal_space == None:
            goal_space = args.goal_space
        else:
            raise Exception("Must Specify the goal space as a list")

        self.goal_space = goal_space

        self.r_path = save_dir + "r" + exp_no
        self.c_path = save_dir + "c" + exp_no

        self.EVAL_REWARDS = []
        self.EVAL_CONSTRAINTS = []

        self.TRAIN_REWARDS = []
        self.TRAIN_CONSTRAINTS = []



        self.args = args

        #for the time being let's skip the vectorized environment's added complexity in HRL
        self.env = env

        self.G = Goal_Space(goal_space=goal_space, grid_size=self.env.size)
        self.grid_size = self.env.size

        #c = []
        #for i in goal_space:
        #    c.append(self.G.convert_value_to_coordinates(i))
        #print(c)

        self.eval_env = copy.deepcopy(env)


        s = env.reset()
        self.state_dim = s.shape
        self.action_dim = env.action_space.n

        self.goal_dim = self.G.action_shape[0]
        self.goal_state_dim = np.concatenate((s,s)).shape

        # these are the cost conditioned value functions that will be used for reward Q vlaue functions
        self.cost_goal_state_dim = (self.goal_state_dim[0] + 1,)
        self.cost_state_dim = (self.state_dim[0] + 1,)

        self.device = torch.device("cuda" if (torch.cuda.is_available() and  self.args.gpu) else "cpu")

        # set the same random seed in the main launcher
        random.seed(self.args.seed)
        torch.manual_seed(self.args.seed)
        np.random.seed(self.args.seed)
        if self.args.gpu:
            torch.cuda.manual_seed(self.args.seed )

        self.writer = writer

        if self.args.env_name == "grid" or self.args.env_name == "grid_key" or self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid"or self.args.env_name == "puddle":
            self.dqn_meta = OneHotDQN(self.state_dim, self.goal_dim).to(self.device)
            self.dqn_meta_target = OneHotDQN(self.state_dim, self.goal_dim).to(self.device)

            self.dqn_lower = OneHotDQN(self.goal_state_dim, self.action_dim).to(self.device)
            self.dqn_lower_target = OneHotDQN(self.goal_state_dim, self.action_dim).to(self.device)

            # create more networks for lower level
            self.cost_lower_model = OneHotDQN(self.goal_state_dim, self.action_dim).to(self.device)
            self.review_lower_model = OneHotValueNetwork(self.goal_state_dim).to(self.device)
            self.cost_lower_value_model = OneHotDQN(self.state_dim, self.goal_dim).to(self.device)

            #self.target_lower_cost_model = OneHotDQN(self.goal_state_dim, self.action_dim).to(self.device)
            #self.target_lower_review_model = OneHotValueNetwork(self.goal_state_dim).to(self.device)

            #self.target_lower_cost_model.load_state_dict(self.cost_lower_model.state_dict())
            #self.target_lower_review_model.load_state_dict(self.review_lower_model.state_dict())

            # create more networks for higher level
            self.cost_upper_model = OneHotDQN(self.state_dim, self.goal_dim).to(self.device)
            self.review_upper_model = OneHotValueNetwork(self.state_dim).to(self.device)

            #self.target_upper_cost_model = OneHotDQN(self.state_dim, self.goal_dim).to(self.device)
            #self.target_upper_review_model = OneHotValueNetwork(self.state_dim).to(self.device)

            #self.target_upper_cost_model.load_state_dict(self.cost_upper_model.state_dict())
            #self.target_upper_review_model.load_state_dict(self.review_upper_model.state_dict())


        else:
            raise Exception("not implemented yet!")

        # copy parameters
        self.dqn_meta_target.load_state_dict(self.dqn_meta.state_dict())
        self.dqn_lower_target.load_state_dict(self.dqn_lower.state_dict())

        self.optimizer_meta = torch.optim.Adam(self.dqn_meta.parameters(), lr=self.args.lr)
        self.optimizer_lower = torch.optim.Adam(self.dqn_lower.parameters(), lr=self.args.lr)
        #for lower cost value function
        self.review_lower_optimizer = optim.Adam(self.review_lower_model.parameters(), lr=self.args.cost_reverse_lr)
        # for lower cost q function
        self.critic_lower_optimizer = optim.Adam(self.cost_lower_model.parameters(),lr=self.args.cost_q_lr)
        self.value_critic_lower_optimizer = optim.Adam(self.cost_lower_value_model.parameters(), lr=self.args.cost_q_lr)
        #for upper cost value function
        self.review_upper_optimizer = optim.Adam(self.review_upper_model.parameters(), lr=self.args.cost_reverse_lr)
        # for upper cost q function
        #self.critic_upper_optimizer = optim.Adam(self.cost_upper_model.parameters(),lr=self.args.cost_q_lr)
        self.critic_upper_optimizer = optim.Adam(self.cost_upper_model.parameters(), lr=self.args.lr)

        self.total_steps = 0
        self.total_lower_time_steps = 0
        self.total_meta_time_steps = 0
        self.num_episodes = 0
        #50000
        #different epsilon for different levels
        #self.eps_u_decay = LinearSchedule(300000 * 200, 0.01, 1.0)
        #self.eps_l_decay = LinearSchedule(50000 * 200, 0.01, 1.0)

        self.eps_u_decay = LinearSchedule(40000 * 200, 0.01, 1.0)
        self.eps_l_decay = LinearSchedule(30000 * 200, 0.01, 1.0)

        #decide on weather to use total step or just the meta steps for this annealing
        self.eps_u = self.eps_u_decay.value(self.total_steps)
        self.eps_l = self.eps_l_decay.value(self.total_lower_time_steps)

        # for storing resutls
        self.results_dict = {
            "train_rewards" : [],
            "train_constraints" : [],
            "eval_rewards" : [],
            "eval_constraints" : [],
        }

        self.cost_indicator = "none"
        if "grid" in self.args.env_name:
            self.cost_indicator = 'pit'
        elif self.args.env_name == "four_rooms":
            self.cost_indicator = 'pit'
        elif "puddle" in self.args.env_name:
            self.cost_indicator = 'pit'
        else:
            raise Exception("not implemented yet")

    def pi_meta(self, state, greedy_eval=False):
        """
        choose goal based on the current policy
        """
        with torch.no_grad():

            self.eps_u = self.eps_u_decay.value(self.total_steps)
            # to choose random goal or not
            if (random.random() > self.eps_u) or greedy_eval:
                q_value = self.dqn_meta(state)

                # chose the max/greedy actions
                goal = np.array([q_value.max(0)[1].cpu().numpy()])
            else:
                goal = np.random.randint(0, high=self.goal_dim, size = (self.args.num_envs, ))

        return goal

    def pi_lower(self, state, goal, greedy_eval=False):
        """
        take the action based on the current policy
        """
        state_goal = torch.cat((state, goal))

        self.eps_l = self.eps_l_decay.value(self.total_lower_time_steps)
        with torch.no_grad():
            # to take random action or not
            if (random.random() > self.eps_l) or greedy_eval:
                q_value = self.dqn_lower(state_goal)
                # chose the max/greedy actions
                action = np.array([q_value.max(0)[1].cpu().numpy()])

                #print(action)
                #print("action_greedy")
            else:
                action = np.random.randint(0, high=self.action_dim, size = (self.args.num_envs, ))
                #print(action)
                #print("action_random")
        return action

    def safe_deterministic_pi_lower(self, state, goal, goal_discrete, current_cost=None, greedy_eval=False):
        """
        Things to figure out:
        Now the lower level cost estimate depends on both the state and goal( which is not decided until we select one
        """


        state_goal = torch.cat((state, goal))

        with torch.no_grad():
            # to take random action or not
            self.eps_l = self.eps_l_decay.value(self.total_lower_time_steps)
            if (random.random() > self.eps_l) or greedy_eval:
                # No random action
                q_value = self.dqn_lower(state_goal)

                cost_q_val = self.cost_lower_model(state_goal)
                cost_r_val = self.review_lower_model(state_goal)

                if current_cost != None:
                    objective = q_value - self.lam*current_cost
                else:
                    objective = q_value - self.lam*cost_q_val

                #take the action that minimized the cost and get to the goal. There is no constraints imposed in this case
                action = np.array([objective.max(0)[1].cpu().numpy()])
                return action

            else:
                # create an array of random indices, for all the environments
                action = np.random.randint(0, high=self.action_dim, size = (self.args.num_envs, ))

        return action

    def safe_deterministic_pi_upper(self, state, current_cost=0.0, greedy_eval=False):
        """
        take the action based on the current policy
        d_low: cost allocated for the current low level episode
        """

        with torch.no_grad():
            # to take random action or not
            self.eps_l = self.eps_l_decay.value(self.total_lower_time_steps)
            if (random.random() > self.eps_l) or greedy_eval:
                # No random action
                q_value = self.dqn_meta(state)

                # Q_D(s,a)
                cost_v_val = self.cost_lower_value_model(state)

                cost_q_val_upper = self.cost_upper_model(state)
                cost_r_val_upper = self.review_upper_model(state)

                quantity_1 = cost_q_val_upper + cost_r_val_upper
                quantity_2 = self.args.d0 + (cost_v_val)

                """
                print(cost_v_val, "a")
                print(cost_q_val_upper)
                print(cost_r_val_upper)
                print(quantity_1, quantity_2)
                """


                #quantity_2 = self.args.d0 + (current_cost)
                # find the action set that satisfies the constraints
                # create the filtered mask here
                constraint_mask = torch.le(quantity_1, quantity_2).float().squeeze(0)

                #print(q_value)
                #print(constraint_mask)
                #print(cost_v_val)
                #print(cost_q_val_upper + cost_r_val_upper)

                filtered_Q = (q_value + 1000.0) * (constraint_mask)

                filtered_goal = np.array([filtered_Q.max(0)[1].cpu().numpy()])
                # alt action to take if infeasible solution
                # minimize the cost
                alt_goal = np.array([(-1. * cost_q_val_upper).max(0)[1].cpu().numpy()])

                c_sum = constraint_mask.sum(0)
                goal_mask = (c_sum == torch.zeros_like(c_sum)).cpu().numpy()

                goal = (1 - goal_mask) * filtered_goal + goal_mask * alt_goal

                return goal

            else:
                # create an array of random indices, for all the environments
                goal = np.random.randint(0, high=self.goal_dim, size=(self.args.num_envs,))

        return goal


    def compute_n_step_returns(self, next_value, rewards, masks):
        """
        n-step SARSA returns
        """


        R = next_value
        returns = []
        for step in reversed(range(len(rewards))):
            R = rewards[step] + self.args.gamma * R * masks[step]
            returns.insert(0, R)

        return returns

    def compute_reverse_n_step_returns(self, prev_value, costs, begin_masks):
        """
        n-step SARSA returns (backward in time)
        """

        R = prev_value
        returns = []
        for step in range(len(costs)):
            R = costs[step] + self.args.gamma * R * begin_masks[step]

            returns.append(R)
        return returns

    def log_episode_stats(self, ep_reward, ep_constraint, F, C_l):
        """
        log the stats for environment performance
        """
        # log episode statistics
        self.TRAIN_REWARDS.append(ep_reward)
        self.TRAIN_CONSTRAINTS.append(ep_constraint)


        log(
            'Num Episode {}\t'.format(self.num_episodes) + \
            'avg_train_reward: {:.2f}\t'.format(np.mean(self.TRAIN_REWARDS[-100:])) +\
            'avg_train_constraint: {:.2f}\t'.format(np.mean(self.TRAIN_CONSTRAINTS[-100:])) +\
            'lower level reward: ' + str(F) + " lower level cost: " + str(C_l)
                )
        #'E[R]: {:.2f}\t'.format(ep_reward) +\
        #'E[C]: {:.2f}\t'.format(ep_constraint) +\

    def run(self):
        """
        Learning happens here
        """
        self.total_steps = 0
        self.total_lower_time_steps = 0
        self.total_meta_time_steps = 0
        self.eval_steps = 0

        # reset state and env
        # reset exploration porcess
        state = self.env.reset()
        state = torch.FloatTensor(state).to(device=self.device)
        previous_state = state
        current_cost = torch.zeros(self.args.num_envs, 1).float().to(self.device)

        #total episode reward, length for logging purposes
        self.ep_reward = 0
        self.ep_len = 0
        self.ep_constraint = 0
        start_time = time.time()


        self.global_intrinsic_reward = 100
        self.per_step_penalty = -1


        while self.num_episodes < self.args.num_episodes:


            next_state = None
            done = None

            states_u      = []
            actions_u     = []


            rewards     = []
            done_masks  = []
            constraints = []

            IR_t = []
            Goals_t = []
            CS_t = []
            T_t = []



            eps_r_value_U = []
            eps_f_q_value_U = []

            eps_cost_L = []
            eps_cost_U = []

            eps_f_value_L = []
            eps_f_q_value_L = []

            eps_value_g1 = []
            eps_value_g2 = []
            eps_value_g3 = []

            t_upper = 0

             # this is so that we can compute n-step return. But in the current case n is 1 for upper so list will only have one value
            #prev_states_u.append(state)

            e_l = 0

            d_m = []

            values_upper = []
            rewards_upper = []
            constraints_upper = []
            done_masks = []
            begin_mask_upper = []
            prev_states_u = []

            cost_q_upper = []
            cost_r_upper = []

            while not done:
                e_l += 1


                if t_upper == 0:
                    begin_mask_u = True
                else:
                    begin_mask_u = False

                t_upper += 1

                #goal = self.pi_meta(state=state)
                goal = self.safe_deterministic_pi_upper(state)

                if self.args.env_name == "grid_key":
                    x_g, y_g = self.G.convert_value_to_coordinates(self.G.goal_space[goal.item()])
                    Goals_t.append((x_g, y_g, self.G.goal_space[goal.item()]))

                    goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
                    goal_hot_vec = self.G.covert_value_to_hot_vec(goal)
                    goal_hot_vec = torch.FloatTensor(goal_hot_vec).to(self.device)
                elif self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid":
                    goal_hot_vec = self.env.conver_state_num_state(self.goal_space[goal.item()])
                    goal_hot_vec = torch.FloatTensor(goal_hot_vec).to(self.device)

                    Goals_t.append(self.goal_space[goal.item()])

                    goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
                elif self.args.env_name == "puddle":
                    Goals_t.append(self.G.goal_space[goal.item()])

                    goal_np = self.goal_space[goal.item()]
                    goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
                    goal_hot_vec = torch.FloatTensor(goal_np).to(self.device)


                q_values_upper = self.dqn_meta(state)
                Q_value_upper = q_values_upper.gather(0, goal[0])

                cost_values_upper = self.cost_upper_model(state)
                Cost_value_Upper = cost_values_upper.gather(0, goal[0])
                Review_value_Upper = self.review_upper_model(state)


                #an indicator that is used to terminate the lower level episode
                t_lower = 0

                R = 0
                C = 0

                upper_cost_sum = 0

                F_l = []
                C_l = []



                # debug parameters
                eps_f_q_value_U.append(Cost_value_Upper.item())
                eps_r_value_U.append(Review_value_Upper.item())

                goal1 = torch.LongTensor([0])  # random
                goal2 = torch.LongTensor([1])  # key
                goal3 = torch.LongTensor([2])  # goal

                eps_value_g1.append(q_values_upper.gather(0, goal1).item())
                eps_value_g2.append(q_values_upper.gather(0, goal2).item())
                eps_value_g3.append(q_values_upper.gather(0, goal3).item())



                while t_lower <= self.args.max_ep_len_l-1:

                    instrinc_rewards = []  # for low level n-step
                    values_lower     = []
                    done_masks_lower = []
                    constraints_lower = []
                    begin_mask_lower = []
                    cost_q_lower = []
                    cost_r_lower = []
                    cost_v_lower = []
                    prev_states_l = []

                    eps_cost_estimate_l = []
                    eps_action_mask_l = []
                    esp_cost_l = []

                    eps_r_value_l = []
                    eps_f_q_value_l = []
                    eps_f_value_l = []


                    C_lower = 0
                    F_lower = 0
                    lower_cost_sum = 0

                    c_temp = 0
                    for n_l in range(self.args.traj_len_l):

                        #action = self.safe_deterministic_pi_lower(state=state, goal=goal_hot_vec, goal_discrete=goal, current_cost=current_cost)
                        action = self.safe_deterministic_pi_lower(state=state, goal=goal_hot_vec, goal_discrete=goal, current_cost=None)


                        if self.args.env_name == "grid_key":
                            next_state, reward, done, info = self.env.step(action.item())
                        elif self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid" or self.args.env_name == "puddle":
                            next_state, reward, done, info = self.env.step(action)

                        #instrinc_reward = self.G.intrisic_reward(current_state=next_state,
                        #                                            goal_state=goal_hot_vec)

                        if t_lower == 0:
                            begin_mask_l = True
                        else:
                            begin_mask_l = False


                        next_state = torch.FloatTensor(next_state).to(self.device)

                        if self.args.env_name == "grid_key":
                            done_l = self.G.validate(current_state=next_state, goal_state=goal_hot_vec)  #this is to validate the end of the lower level episode
                        elif self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid"  :
                            done_l = self.G.validate(current_state=next_state, goal_state=goal_hot_vec)
                        elif self.args.env_name == "puddle":
                            done_l = np.linalg.norm((np.array(next_state.tolist()) - np.array(goal_np)), ord=1) < self.env.goal_threshold

                        if done_l:
                            instrinc_reward =self.global_intrinsic_reward
                        else:
                            instrinc_reward = self.per_step_penalty

                        action = torch.LongTensor(action).unsqueeze(1).to(self.device)
                        current_cost = torch.FloatTensor([info[self.cost_indicator] * (1.0 - done)]).unsqueeze(1).to(self.device)

                        #these are the values used to train the lower level
                        R += reward
                        C += info[self.cost_indicator]
                        C_lower += info[self.cost_indicator]
                        c_temp += info[self.cost_indicator]

                        C_lower = torch.FloatTensor([C_lower]).unsqueeze(1).to(self.device)
                        F_lower += instrinc_reward
                        lower_cost_sum += info[self.cost_indicator]
                        upper_cost_sum += info[self.cost_indicator]

                        #for training logging purposes
                        self.ep_len += 1
                        self.ep_constraint += info[self.cost_indicator]
                        self.ep_reward += reward

                        state_goal = torch.cat((state, goal_hot_vec))

                        q_values_lower = self.dqn_lower(state=state_goal)
                        Q_value_lower = q_values_lower.gather(0, action[0])



                        cost_values_lower = self.cost_lower_model(state=state_goal)
                        Cost_value = cost_values_lower.gather(0, action[0])
                        Review_value_lower = self.review_lower_model(state=state_goal)
                        Value_lower = self.cost_lower_value_model(state=state).gather(0, goal[0])

                        #if t_lower == 0:
                        #    constraints_upper.append(Value_lower)

                        values_lower.append(Q_value_lower)
                        instrinc_rewards.append(instrinc_reward)
                        done_masks_lower.append((1 - done_l))
                        constraints_lower.append(info[self.cost_indicator])
                        begin_mask_lower.append((1-begin_mask_l))
                        cost_q_lower.append(Cost_value)
                        cost_r_lower.append(Review_value_lower)
                        cost_v_lower.append(Value_lower)

                        #DEBUG STUFF
                        esp_cost_l.append(lower_cost_sum)
                        eps_f_q_value_l.append(Cost_value.item())
                        eps_f_value_l.append(Value_lower.item())
                        eps_r_value_l.append(Review_value_lower.item())

                        t_lower += 1
                        self.total_steps += 1
                        self.total_lower_time_steps += 1

                        previous_state = state
                        state = next_state

                        prev_states_l.append(previous_state)

                        #break if goal is current_state or the if the main episode terminated
                        if done or done_l:

                            break

                        if t_lower > self.args.max_ep_len_l-1:
                            break

                    F_l.append(F_lower)
                    C_l.append(C_lower)

                    x_c, y_c = self.G.convert_value_to_coordinates(self.G.convert_hot_vec_to_value(next_state).item())


                    next_state_goal = torch.cat((next_state, goal_hot_vec))
                    #next_state_goal_cost = torch.cat((torch.cat((next_state, goal_hot_vec)), lower_cost_constraint.detach()))

                    #next_action = self.safe_deterministic_pi_lower(state=next_state, goal=goal_hot_vec, goal_discrete=goal,  current_cost=current_cost)
                    next_action = self.safe_deterministic_pi_lower(state=next_state, goal=goal_hot_vec, goal_discrete=goal, current_cost=None)
                    next_action = torch.LongTensor(next_action).unsqueeze(1).to(self.device)

                    #update Reward Q value function

                    next_values = self.dqn_lower(next_state_goal)
                    Next_Value = next_values.gather(0, next_action[0])


                    target_Q_values_lower = self.compute_n_step_returns(Next_Value, instrinc_rewards, done_masks_lower)
                    Q_targets_lower = torch.cat(target_Q_values_lower).detach()
                    Q_values_lower = torch.cat(values_lower)

                    loss_lower = F.mse_loss(Q_values_lower, Q_targets_lower)

                    self.optimizer_lower.zero_grad()
                    loss_lower.backward()
                    self.optimizer_lower.step()

                    #update cost Q value function
                    next_c_value = self.cost_lower_model(next_state_goal)
                    Next_c_value = next_c_value.gather(0, next_action[0])

                    cq_targets = self.compute_n_step_returns(Next_c_value, constraints_lower, done_masks_lower)
                    C_q_targets = torch.cat(cq_targets).detach()
                    C_q_vals = torch.cat(cost_q_lower)

                    cost_critic_loss_lower = F.mse_loss(C_q_vals, C_q_targets)
                    self.critic_lower_optimizer.zero_grad()
                    cost_critic_loss_lower.backward()
                    self.critic_lower_optimizer.step()

                    # For the constraints (reverse)
                    previous_state_goal = torch.cat((prev_states_l[0], goal_hot_vec))
                    prev_value = self.review_lower_model(previous_state_goal)


                    c_r_targets = self.compute_reverse_n_step_returns(prev_value, constraints_lower, begin_mask_lower)
                    C_r_targets = torch.cat(c_r_targets).detach()
                    C_r_vals = torch.cat(cost_r_lower)



                    cost_review_loss = F.mse_loss(C_r_vals, C_r_targets)
                    self.review_lower_optimizer.zero_grad()
                    cost_review_loss.backward()
                    self.review_lower_optimizer.step()

                    next_v_value = self.cost_lower_value_model(next_state).gather(0, goal[0])
                    cv_targets = self.compute_n_step_returns(next_v_value, constraints_lower, done_masks_lower)
                    C_v_targets = torch.cat(cv_targets).detach()
                    C_v_vals = torch.cat(cost_v_lower)

                    cost_value_critic_loss_lower = F.mse_loss(C_v_vals, C_v_targets)
                    self.value_critic_lower_optimizer.zero_grad()
                    cost_value_critic_loss_lower.backward()
                    self.value_critic_lower_optimizer.step()

                    if done:


                        break


                    #if goal.item() == 1:
                    #    print(lower_cost_sum, C, t_lower)
                eps_cost_U.append(upper_cost_sum)
                eps_f_q_value_L.append(eps_f_q_value_l)
                eps_f_value_L.append(eps_f_value_l)

                prev_states_u.append(previous_state)

                values_upper.append(Q_value_upper)
                rewards_upper.append(R)
                constraints_upper.append(C)
                cost_q_upper.append(Cost_value_Upper)
                cost_r_upper.append(Review_value_Upper)
                done_masks.append((1 - done))
                begin_mask_upper.append((1 - begin_mask_u))

                d_m.append(done)

                #CS_t.append((x_c, y_c))
                T_t.append(t_lower)

                #if self.num_episodes%100 == 0:
                #    print(constraints_upper, len(prev_states_u))

                if done:

                    # training logging
                    if self.num_episodes % 100 == 0:
                        self.log_episode_stats(ep_reward=self.ep_reward, ep_constraint=self.ep_constraint, F=F_l,
                                               C_l=C_l)

                    if self.num_episodes % 500 == 0:
                        log("Goal State: " + " " + str(Goals_t) + " Current State: " + str(CS_t))
                        # log("No of Higher Eps: " +  str(len(Goals_t)) + " No of lower eps: " + str(T_t)  + " Cost Allocation(future, lower) " + str(Cost_Alloc))

                    # evaluation logging
                    if self.num_episodes % self.args.eval_every == 0:
                        # self.save() #save models

                        #path = self.save_dir + "policy_" + self.exp_no + "/" + "z_" + str(self.num_episodes // 1000)
                        #self.save(path=path)

                        p1 = self.save_dir + "cost_U_" + self.exp_no
                        p2 = self.save_dir + "cost_L_" + self.exp_no
                        p3 = self.save_dir + "f_value_l" + self.exp_no
                        p4 = self.save_dir + "f_q_value_l" + self.exp_no
                        p5 = self.save_dir + "r_value_u" + self.exp_no
                        p6 = self.save_dir + "f_q_value_u" + self.exp_no

                        p7 = self.save_dir + "value_g1_" + self.exp_no
                        p8 = self.save_dir + "value_g2_" + self.exp_no
                        p9 = self.save_dir + "value_g3_" + self.exp_no

                        """
                        torch.save(self.cost_U, p1)
                        torch.save(self.cost_L, p2)

                        torch.save(self.f_value_l, p3)
                        torch.save(self.f_q_value_l, p4)

                        torch.save(self.r_value_u, p5)
                        torch.save(self.f_q_value_u, p6)

                        torch.save(self.value_G1, p7)
                        torch.save(self.value_G2, p8)
                        torch.save(self.value_G3, p9)
                        """
                        eval_reward, eval_constraint, IR, Goals, CS = self.eval()

                        print("Epsilon Upper and Lower:" + str(self.eps_u) + ", " + str(self.eps_l))

                        self.EVAL_REWARDS.append(eval_reward)
                        self.EVAL_CONSTRAINTS.append(eval_constraint)

                        torch.save(self.EVAL_REWARDS, self.r_path)
                        torch.save(self.EVAL_CONSTRAINTS, self.c_path)

                        log('--------------------------------------------------------------------------------------------------------')
                        log("Intrisic Reward: " + str(IR) + " Goal: " + str(Goals) + " Current State: " + str(CS))
                        log(
                            'Episode: {}\t'.format(self.num_episodes) + \
                            'avg_eval_reward: {:.2f}\t'.format(np.mean(self.EVAL_REWARDS[-10:])) + \
                            'avg_eval_constraint: {:.2f}\t'.format(np.mean(self.EVAL_CONSTRAINTS[-10:]))
                        )
                        log('--------------------------------------------------------------------------------------------------------')

                    self.num_episodes += 1
                    # resting episode rewards
                    self.ep_reward = 0
                    self.ep_len = 0
                    self.ep_constraint = 0

                    state = self.env.reset()  # reset
                    state = torch.FloatTensor(state).to(device=self.device)
                    break  # this break is to terminate the higher tier episode as the episode is now over

            next_goal = self.pi_meta(next_state)
            next_goal = torch.LongTensor(next_goal).unsqueeze(1).to(self.device)

            next_values = self.dqn_meta(next_state)
            Next_Value = next_values.gather(0, next_goal[0])



            target_Q_values_upper = self.compute_n_step_returns(Next_Value, rewards_upper, done_masks)
            Q_targets_upper = torch.cat(target_Q_values_upper).detach()
            Q_values_upper = torch.cat(values_upper)

            loss_upper = F.mse_loss(Q_values_upper, Q_targets_upper)
            self.optimizer_meta.zero_grad()
            loss_upper.backward()
            self.optimizer_meta.step()

            # update cost Q value function upper
            next_c_value = self.cost_upper_model(next_state)
            Next_c_value = next_c_value.gather(0, next_goal[0])




            cq_targets = self.compute_n_step_returns(Next_c_value, constraints_upper, done_masks)
            C_q_targets = torch.cat(cq_targets).detach()
            C_q_vals = torch.cat(cost_q_upper)

            #print(Next_c_value.item(), constraints_upper[0], C_q_vals.item() )

            cost_critic_loss_upper = F.mse_loss(C_q_vals, C_q_targets)
            self.critic_upper_optimizer.zero_grad()
            cost_critic_loss_upper.backward()
            self.critic_upper_optimizer.step()

            # For the constraints (reverse) upper
            previous_state = prev_states_u[0]
            prev_value = self.review_upper_model(previous_state)

            c_r_targets = self.compute_reverse_n_step_returns(prev_value, constraints_upper, begin_mask_upper)
            C_r_targets = torch.cat(c_r_targets).detach()
            C_r_vals = torch.cat(cost_r_upper)

            """
            if self.num_episodes%200 == 0:
                print(e_l)
                print(d_m, goal.item())
                print("------------------------------------------")
                print("Forward")
                print(constraints_upper, Next_c_value)
                print(C_q_targets, C_q_vals)
                print("Backward")
                print(constraints_upper, prev_value)
                print(C_r_targets, C_r_vals)
            #print(prev_value.item(), constraints_upper[0], C_r_vals.item())
            """

            cost_review_loss = F.mse_loss(C_r_vals, C_r_targets)
            self.review_upper_optimizer.zero_grad()
            cost_review_loss.backward()
            self.review_upper_optimizer.step()






            self.cost_L.append(eps_cost_L)
            self.cost_U.append(eps_cost_U)



            self.f_value_l.append(eps_f_value_L)
            self.f_q_value_l.append(eps_f_q_value_L)

            self.r_value_u.append(eps_r_value_U)
            self.f_q_value_u.append(eps_f_q_value_U)
            self.value_G1.append(eps_value_g1)
            self.value_G2.append(eps_value_g2)
            self.value_G3.append(eps_value_g3)



    def eval(self):
        """
                    evaluate the current policy and log it
                    """

        avg_reward = []
        avg_constraint  = []

        state = self.eval_env.reset()
        previous_state = torch.FloatTensor(state).to(self.device)
        state = torch.FloatTensor(state).to(self.device)
        done = False
        ep_reward = 0
        ep_constraint = 0
        ep_len = 0
        start_time = time.time()

        IR = []
        Goals = []
        CS = []


        current_cost = torch.zeros(self.args.num_envs, 1).float().to(self.device)

        while not done:

            # convert the state to tensor


            # get the goal
            goal = self.safe_deterministic_pi_upper(state=state, greedy_eval=True)

            if self.args.env_name == "grid_key":
                x_g, y_g = self.G.convert_value_to_coordinates(self.G.goal_space[goal.item()])

                goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
                goal_hot_vec = self.G.covert_value_to_hot_vec(goal)
                goal_hot_vec = torch.FloatTensor(goal_hot_vec).to(self.device)
            elif self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid":
                goal_hot_vec = self.env.conver_state_num_state(self.goal_space[goal.item()])
                goal_hot_vec = torch.FloatTensor(goal_hot_vec).to(self.device)

                Goals.append(self.goal_space[goal.item()])
                goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
            elif self.args.env_name == "puddle":

                goal_np = self.goal_space[goal.item()]
                goal = torch.LongTensor(goal).unsqueeze(1).to(self.device)
                goal_hot_vec = torch.FloatTensor(goal_np).to(self.device)

            t_lower = 0
            ir = 0
            while t_lower <= self.args.max_ep_len_l-1:

                #action = self.safe_deterministic_pi_lower(state=state, goal=goal_hot_vec, goal_discrete=goal, current_cost=current_cost, greedy_eval=True)
                action = self.safe_deterministic_pi_lower(state=state, goal=goal_hot_vec, goal_discrete=goal,
                                                          current_cost=None, greedy_eval=True)
                # print(torch.equal(state, previous_state), self.G.convert_hot_vec_to_value(state), self.G.convert_hot_vec_to_value(goal_hot_vec))
                # print(self.dqn_lower(torch.cat((state, goal_hot_vec))), t_lower)

                if self.args.env_name == "grid_key":
                    next_state, reward, done, info = self.env.step(action=action.item())
                elif self.args.env_name == "four_rooms" or self.args.env_name == "complex-grid"or self.args.env_name == "puddle":
                    next_state, reward, done, info = self.env.step(action=action)

                ep_reward += reward
                ep_len += 1
                ep_constraint += info[self.cost_indicator]


                next_state = torch.FloatTensor(next_state).to(self.device)

                # update the state
                previous_state = state
                state = next_state

                current_cost = torch.FloatTensor([info[self.cost_indicator] * (1.0 - done)]).unsqueeze(1).to(self.device)

                instrinc_reward = self.G.intrisic_reward(current_state=next_state,
                                                         goal_state=goal_hot_vec)
                ir += instrinc_reward
                t_lower += 1

                done_l = self.G.validate(current_state=next_state, goal_state=goal_hot_vec)
                if done_l or done:
                    break

            IR.append(ir)

            #x_c, y_c = self.G.convert_value_to_coordinates(self.G.convert_hot_vec_to_value(next_state).item())

            #CS.append((x_c, y_c))


        avg_reward.append(ep_reward)
        avg_constraint.append(ep_constraint)

        #print(avg_reward, avg_constraint)
        print(CS)
        return np.mean(avg_reward), np.mean(avg_constraint), IR, Goals, CS


    def save(self):
        path = self.save_dir + "z" + self.exp_no

        torch.save(self.dqn_meta.state_dict(), path + "_rq_meta")
        torch.save(self.dqn_lower.state_dict(), path + "_rq_lower")

        torch.save(self.cost_lower_model.state_dict(), path + "_cq_lower")
        torch.save(self.review_lower_model.state_dict(), path + "_cv_lower")
        torch.save(self.cost_upper_model.state_dict(), path + "_cq_upper")
        torch.save(self.review_upper_model.state_dict(), path + "_cv_upper")

    def save(self, path):
        path = path

        torch.save(self.dqn_meta.state_dict(), path + "_rq_meta")
        torch.save(self.dqn_lower.state_dict(), path + "_rq_lower")

        torch.save(self.cost_lower_model.state_dict(), path + "_cq_lower")
        torch.save(self.cost_lower_value_model.state_dict(), path + "_cfv_lower")
        #torch.save(self.review_lower_model.state_dict(), path + "_cv_lower")
        torch.save(self.cost_upper_model.state_dict(), path + "_cq_upper")
        torch.save(self.review_upper_model.state_dict(), path + "_crv_upper")
    def load(self):

        path = self.save_dir + "z" + self.exp_no
        print(path)
        self.dqn_meta.load_state_dict(torch.load(path + "_rq_meta"))
        self.dqn_lower.load_state_dict(torch.load( path + "_rq_lower"))

        self.cost_lower_model.load_state_dict(torch.load( path + "_cq_lower"))
        self.review_lower_model.load_state_dict(torch.load(path + "_cv_lower"))
        self.cost_upper_model.load_state_dict(torch.load(path + "_cq_upper"))
        self.review_upper_model.load_state_dict(torch.load(path + "_cv_upper"))

    #this function is for debugging
    def load(self, eps_no):

        eps_no = str(eps_no)
        path = self.save_dir + "z_" + eps_no
        print(path)
        self.dqn_meta.load_state_dict(torch.load(path + "_rq_meta"))
        self.dqn_lower.load_state_dict(torch.load( path + "_rq_lower"))

        self.cost_lower_model.load_state_dict(torch.load( path + "_cq_lower"))
        self.cost_lower_value_model.load_state_dict(torch.load(path + "_cfv_lower"))
        #self.review_lower_model.load_state_dict(torch.load(path + "_cv_lower"))
        self.cost_upper_model.load_state_dict(torch.load(path + "_cq_upper"))
        self.review_upper_model.load_state_dict(torch.load(path + "_crv_upper"))