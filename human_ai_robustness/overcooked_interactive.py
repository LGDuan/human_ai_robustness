import pygame, random, time
from argparse import ArgumentParser

from overcooked_ai_py.agents.agent import StayAgent, RandomAgent, AgentFromPolicy
from human_ai_robustness.agent import GreedyHumanModel_pk, ToMModel
from overcooked_ai_py.mdp.overcooked_mdp import OvercookedGridworld, Direction, Action
from overcooked_ai_py.mdp.overcooked_env import OvercookedEnv
from overcooked_ai_py.planning.planners import MediumLevelPlanner
from overcooked_ai_py.utils import load_dict_from_file  # , get_max_iter

from human_aware_rl.utils import get_max_iter

from concurrent.futures import ThreadPoolExecutor

pool = ThreadPoolExecutor(3)

UP = 273
RIGHT = 275
DOWN = 274
LEFT = 276
SPACEBAR = 32

cook_time = 20
start_order_list = 100 * ['any']
step_time_ms = 150

no_counters_params = {
    'start_orientations': False,
    'wait_allowed': False,
    'counter_goals': [],
    'counter_drop': [],
    'counter_pickup': [],
    'same_motion_goals': True
}

one_counter_params = {
    'start_orientations': False,
    'wait_allowed': False,
    'counter_goals': [],  # Set later
    'counter_drop': [],  # Set later
    'counter_pickup': [],
    'same_motion_goals': True
}


class App:
    """Class to run an Overcooked Gridworld game, leaving one of the players as fixed.
    Useful for debugging. Most of the code from http://pygametutorials.wikidot.com/tutorials-basic."""

    def __init__(self, env, agent, my_index, time_limit):
        self._running = True
        self._display_surf = None
        self.env = env
        self.agent = agent
        self.my_index = my_index
        self.other_index = 1 - self.my_index
        self.size = self.weight, self.height = 1, 1
        self.future_action = None
        self.done = False
        self.time_limit = time_limit

    def on_init(self):
        pygame.init()

        # self.agent.set_mdp(self.env.mdp)

        print(self.env)
        self._display_surf = pygame.display.set_mode(self.size, pygame.HWSURFACE | pygame.DOUBLEBUF)
        self._running = True

    def on_event(self, event):
        s_since_start = (time.time() - self.start_time)
        if (event is not None and event.type == pygame.QUIT) or self.done or (s_since_start > self.time_limit):
            self._running = False
        elif event is None or event.type == pygame.KEYDOWN:
            if event is None:
                action = Action.STAY
            elif event.type == pygame.KEYDOWN:
                pressed_key = event.dict['key']
                action = None

                if pressed_key == UP or pressed_key == ord('w'):
                    action = Direction.NORTH
                elif pressed_key == RIGHT or pressed_key == ord('d'):
                    action = Direction.EAST
                elif pressed_key == DOWN or pressed_key == ord('s'):
                    action = Direction.SOUTH
                elif pressed_key == LEFT or pressed_key == ord('a'):
                    action = Direction.WEST
                elif pressed_key == SPACEBAR:
                    action = Action.INTERACT

            # If the wrong key is pressed then just stay
            if action not in Action.ALL_ACTIONS:
                action = Action.STAY

            self.done = self.step_env(action)

    def step_env(self, my_action):
        if self.future_action is None:
            agent_action, _ = self.agent.action(self.env.state)
        else:
            # print(self.future_action.done())
            while not self.future_action.done():
                # print('waiting')
                pass
            agent_action = self.future_action.result()[0]

        if self.my_index == 0:
            joint_action = (my_action, agent_action)
        else:
            joint_action = (agent_action, my_action)

        s_t, r_t, done, info = self.env.step(joint_action)

        self.future_action = pool.submit(self.agent.action, (self.env.state))
        time_left = round(self.time_limit - (time.time() - self.start_time))
        print("Time left: {}".format(time_left))
        print(self.env)
        return done

    def on_loop(self):
        if len(self.events_log) != 0:
            event = self.events_log.pop(0)
            self.events_log = []
            self.on_event(event)
        else:
            self.on_event(None)

    def on_render(self):
        pass

    def on_cleanup(self):
        pygame.quit()

    def on_execute(self):
        if self.on_init() == False:
            self._running = False

        prev_timestep = -1
        self.events_log = []

        self.start_time = time.time()
        while (self._running):
            ms_since_start = (time.time() - self.start_time) * 1000
            self.curr_timestep = ms_since_start // step_time_ms

            self.events_log.extend(pygame.event.get(pygame.KEYDOWN))
            if prev_timestep < self.curr_timestep:
                self.on_loop()

            prev_timestep = self.curr_timestep
            pygame.event.clear(eventtype=pygame.KEYUP)  # Clear KEYUP events from the events queue, as we don't use these

            self.on_render()
        self.on_cleanup()

def setup_game(run_type, run_dir, cfg_run_dir, run_seed, agent_num, agent_index):
    # if run_type in ["pbt", "ppo"]:
    #     # TODO: Add testing for this
    #     run_path = "data/" + run_type + "_runs/" + run_dir + "/seed_{}".format(run_seed)
    #     # TODO: use get_config_from_pbt_dir if will be split up for the two cases
    #     config = load_dict_from_file(run_path + "/config")
    #
    #     agent_folder = run_path + '/agent' + str(agent_num)
    #     agent_to_load_path = agent_folder + "/pbt_iter" + str(get_max_iter(agent_folder))
    #     agent = get_agent_from_saved_model(agent_to_load_path, config["SIM_THREADS"])
    #
    #     if config["FIXED_MDP"]:
    #         layout_name = config["FIXED_MDP"]
    #         layout_filepath = "data/layouts/{}.layout".format(layout_name)
    #         mdp = OvercookedGridworld.from_file(layout_filepath, config["ORDER_GOAL"], config["EXPLOSION_TIME"], rew_shaping_params=None)
    #         env = OvercookedEnv(mdp)
    #     else:
    #         env = setup_mdp_env(display=False, **config)
    #
    # elif run_type == "bc":
    #     config = get_config_from_pbt_dir(cfg_run_dir)
    #
    #     # Modifications from original pbt config
    #     config["ENV_HORIZON"] = 1000
    #
    #     gym_env, _ = get_env_and_policy_fn(config)
    #     env = gym_env.base_env
    #
    #     model_path = run_dir #'data/bc_runs/test_BC'
    #     agent = get_agent_from_saved_BC(cfg_run_dir, model_path, stochastic=True)

    if run_type == "tom":

        if layout == 'aa':
            layout_name = 'asymmetric_advantages'
        elif layout == 'croom':
            layout_name = 'cramped_room'
        elif layout == 'cring':
            layout_name = 'coordination_ring'
        elif layout == 'cc':
            layout_name = 'counter_circuit'
        else:
            raise ValueError('layout not recognised')

        mdp = OvercookedGridworld.from_layout_name(layout_name, start_order_list=start_order_list,
                                                   cook_time=cook_time, rew_shaping_params=None)
        env = OvercookedEnv(mdp)
        # Doing this means that all counter locations are allowed to have objects dropped on them AND be "goals" (I think!)
        no_counters_params['counter_drop'] = mdp.get_counter_locations()
        no_counters_params['counter_goals'] = mdp.get_counter_locations()
        mlp = MediumLevelPlanner.from_pickle_or_compute(mdp, no_counters_params, force_compute=False)

        # perseverance0 = random.random()
        # teamwork0 = random.random()
        # retain_goals0 = random.random()
        # wrong_decisions0 = random.random() ** 5
        # thinking_prob0 = 1 - random.random() **5
        # path_teamwork0 = 1 - random.random() **2
        # rat_coeff0 = 1+random.random()*3

        prob_thinking_not_moving0 = 0
        retain_goals0 = 0.9
        path_teamwork0 = 1
        rat_coeff0 = 20
        prob_pausing0 = 0.7
        compliance0 = 0.5
        prob_greedy0 = 0.5
        prob_obs_other0 = 0.5
        look_ahead_steps0 = 4

        agent = ToMModel(mlp, prob_random_action=0.06, compliance=compliance0, retain_goals=retain_goals0,
                         prob_thinking_not_moving=prob_thinking_not_moving0, prob_pausing=prob_pausing0,
                         path_teamwork=path_teamwork0, rationality_coefficient=rat_coeff0,
                         prob_greedy=prob_greedy0, prob_obs_other=prob_obs_other0, look_ahead_steps=look_ahead_steps0)
        agent.set_agent_index(agent_index)
        agent.use_OLD_ml_action = False

    else:
        raise ValueError("Unrecognized run type")

    return env, agent


if __name__ == "__main__":
    """
    python human_ai_robustness/overcooked_interactive.py -t tom -l croom -i 0
    """
    parser = ArgumentParser()
    # parser.add_argument("-l", "--fixed_mdp", dest="layout",
    #                     help="name of the layout to be played as found in data/layouts",
    #                     required=True)
    parser.add_argument("-t", "--type", dest="type",
                        help="type of run, (i.e. pbt, bc, ppo, tom, etc)", required=False, default="tom")
    parser.add_argument("-r", "--run_dir", dest="run",
                        help="name of run dir in data/*_runs/", required=False, default="test")
    parser.add_argument("-c", "--config_run_dir", dest="cfg",
                        help="name of run dir in data/*_runs/", required=False)
    parser.add_argument("-s", "--seed", dest="seed", default=0)
    parser.add_argument("-a", "--agent_num", dest="agent_num", default=0)
    parser.add_argument("-i", "--index", dest="my_index", default=0)
    parser.add_argument("-l", "--layout", default='croom')
    parser.add_argument("-tm", "--time_limit", default=30, type=float)

    args = parser.parse_args()
    run_type, run_dir, cfg_run_dir, run_seed, agent_num, my_index, layout, time_limit = args.type, args.run, args.cfg, \
                                                                  int(args.seed), int(args.agent_num), \
                                                                  int(args.my_index), args.layout, args.time_limit
    other_index = 1 - my_index
    env, agent = setup_game(run_type, run_dir, cfg_run_dir, run_seed, agent_num, other_index)

    theApp = App(env, agent, my_index, time_limit)
    theApp.on_execute()