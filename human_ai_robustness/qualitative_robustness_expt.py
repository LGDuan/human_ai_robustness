import time, copy, json
import numpy as np
from argparse import ArgumentParser
import matplotlib.pyplot as plt; plt.rcdefaults()

from overcooked_ai_py.utils import mean_and_std_err
from overcooked_ai_py.agents.agent import AgentPair, RandomAgent, StayAgent
from overcooked_ai_py.mdp.actions import Direction
from overcooked_ai_py.mdp.overcooked_env import OvercookedEnv
from overcooked_ai_py.mdp.overcooked_mdp import OvercookedGridworld, PlayerState, ObjectState, OvercookedState
from overcooked_ai_py.planning.planners import MediumLevelPlanner
from human_aware_rl.ppo.ppo_pop import get_ppo_agent, make_tom_agent, get_ppo_run_seeds, PPO_DATA_DIR
from human_aware_rl.data_dir import DATA_DIR
from human_aware_rl.imitation.behavioural_cloning import get_bc_agent_from_saved
from human_aware_rl.utils import set_global_seed

from human_ai_robustness.agent import ToMModel
from human_ai_robustness.import_person_params import import_manual_tom_params


ALL_LAYOUTS = ["counter_circuit", "coordination_ring", "bottleneck", "room", "centre_objects", "centre_pots"]

no_counters_params = {
    'start_orientations': False,
    'wait_allowed': False,
    'counter_goals': [],
    'counter_drop': [],
    'counter_pickup': [],
    'same_motion_goals': True
}

def get_layout_horizon(layout, horizon_length):
    """Return the horizon for given layout/length of task"""
    # TODO: Clean this function: either make horizon a hardcoded property of each test, or turn this into a global dictionary
    # extra_time = 0 if test_agent.__class__ is ToMModel else 0  # For test runs, e.g. if we want to give the TOM extra time
    extra_time = 0
    if extra_time != 0:
        print('>>>>>>> Extra time = {} <<<<<<<<'.format(extra_time))
    if horizon_length == 'short':
        return extra_time + 10

    elif horizon_length == 'medium':
        if layout in ['coordination_ring', 'centre_pots']:
            return extra_time + 15
        else:
            return extra_time + 20

    elif horizon_length == 'long':
        if layout == 'counter_circuit':
            return extra_time + 30
        elif layout == 'coordination_ring':
            return extra_time + 25

def make_ready_soup_at_loc(loc):
    return ObjectState('soup', loc, ('onion', 3, 20))




###################
# TESTING CLASSES #
###################


class InitialStatesCreator(object):

    def __init__(self, varying_params, constants, mdp):
        self.state_params = varying_params
        self.constants = constants
        self.mdp = mdp

    def get_initial_states(self, display=False):
        states = []

        # TODO: This framework probably needs to be improved some more. Right now it's somewhat arbitrary that
        # the 3 elements of this tuple are H, R, and Objects. We should probably turn it into a dict and 
        # accept other types of thigns too, depending if it's ever used in the tests?
        for variation_params_dict in self.state_params[self.mdp.layout_name]:
            
            # Unpack info from variation params dict
            # TODO: if necessary for other tests to have different variation fields, we should make
            # the variation_params_dict have all possible data pieces and be either {data} or None
            # and then assert that every data piece is either in the variation_params_dict or in the self.constants
            # before proceeding
            # We could then overwrite all None variation_params_dict items (potentially this would require making them
            # lambdas too)
            h_loc = variation_params_dict["h_loc"]
            r_loc = variation_params_dict["r_loc"]

            # Players
            h_state = PlayerState(h_loc, self.constants["h_orientation_fn"](), held_object=self.constants["h_held"](h_loc))
            r_state = PlayerState(r_loc, self.constants["r_orientation_fn"](), held_object=self.constants["r_held"](r_loc))
            players = [h_state, r_state]

            # Objects
            objects = copy.deepcopy(self.constants["objects"])
            if "objects" in variation_params_dict.keys():
                for obj_name, obj_loc_list in variation_params_dict["objects"].items():
                    for obj_loc in obj_loc_list:
                        objects[obj_loc] = (ObjectState(obj_name, obj_loc))

            # Overcooked state
            # TODO: Should have all order lists be None, but seems to break things?
            s = OvercookedState(players, objects, order_list=['any'] * 100).deepcopy()
            states.append(s)

        return states


class AbstractRobustnessTest(object):
    """
    Defines a specific robustness test
    
    # NOTE: For all tests, H_model is on index 0 and trained_agent is on index 1!
    """

    # Constant attributes
    ALL_TEST_TYPES = ["state_robustness", "agent_robustness", "memory"]

    # Attributes meant to be overwitten by subclasses
    valid_layouts = ALL_LAYOUTS
    test_types = None

    def __init__(self, mdp, testing_horizon, trained_agent, trained_agent_type, agent_run_name, num_rollouts_per_initial_state=1, print_info=False, display_runs=False):
        self.mdp = mdp
        self.layout = mdp.layout_name
        self.env_horizon = get_layout_horizon(self.layout, testing_horizon)
        self.num_rollouts_per_initial_state = num_rollouts_per_initial_state

        self.print_info = print_info
        self.display_runs = display_runs

        # Just a string of the name
        self.trained_agent_type = trained_agent_type
        self.agent_run_name = agent_run_name
        self.success_rate = self.evaluate_agent_on_layout(trained_agent)

        assert all(test_type in self.ALL_TEST_TYPES for test_type in self.test_types), "You need to set the self.test_types class attribute for this specific test class, and each test type must be among the following: {}".format(self.test_types)

    def to_dict(self):
        """To enable pickling if one wants to save the test data for later processing"""
        return {
            "layout": self.layout,
            "env_horizon": self.env_horizon,
            "test_types": self.test_types,
            "num_rollouts_per_initial_state": self.num_rollouts_per_initial_state,
            "trained_agent_type": self.trained_agent_type,
            "agent_run_name": self.agent_run_name,
            "success_rate": self.success_rate
        }

    def setup_human_model(self):
        raise NotImplementedError()

    def evaluate_agent_on_layout(self, trained_agent):
        H_model = self.setup_human_model()

        subtest_successes = []

        for initial_state in self.get_initial_states():

            for _ in range(self.num_rollouts_per_initial_state):
                # Check it's a valid state:
                self.mdp._check_valid_state(initial_state)

                # Setup env
                env = OvercookedEnv(self.mdp, start_state_fn=lambda: initial_state, horizon=self.env_horizon)

                # Play with the tom agent from this state and record score
                agent_pair = AgentPair(H_model, trained_agent)
                final_state = env.get_rollouts(agent_pair, num_games=1, final_state=True, display=self.display_runs, info=False)["ep_observations"][0][-1]
                
                if self.print_info:
                    env.state = initial_state
                    print('\nInitial state:\n{}'.format(env))
                    env.state = final_state
                    print('\nFinal state:\n{}'.format(env))

                success = self.is_success(initial_state, final_state)
                subtest_successes.append(success)

                if self.print_info:
                    print(sum(subtest_successes)/len(subtest_successes))
                    print('Subtest successes: {}'.format(subtest_successes))

        return sum(subtest_successes)/len(subtest_successes)

    def is_success(self, final_state):
        raise NotImplementedError()



############
# TEST 1Ai #
############


class Test1ai(AbstractRobustnessTest):
    """
    Pick up a dish from a counter: H blocks dispenser (in layouts with only one dispenser)
    
    Details:
    - 4 different settings for R's location and the location of the dishes
    - Both pots cooking
    - H holding onion facing South; R holding nothing
    - Success: R gets a dish or changes the pot state?

    POSSIBLE ADDITIONS: Give H no object. More positions for R.
    """

    valid_layouts = ['bottleneck', 'room', 'coordination_ring', 'counter_circuit']
    test_types = ["state_robustness"] # TODO: actually check this, currently placeholder

    def get_initial_states(self):
        # NOTE: Given that there are only 4 settings, does that mean that there are only 5 possible success values (0,25,50,75,100)?
        initial_states_params = {
            'counter_circuit': [
                {   "h_loc": (1, 2),     "r_loc": (1, 1),    "objects": { "dish": [(0, 1)]}                 },
                {   "h_loc": (1, 2),     "r_loc": (1, 1),    "objects": { "dish": [(0, 1), (1, 0), (6, 0)]} },
                {   "h_loc": (1, 2),     "r_loc": (6, 1),    "objects": { "dish": [(6, 0)],               } },
                {   "h_loc": (1, 2),     "r_loc": (6, 1),    "objects": { "dish": [(0, 1), (1, 0), (6, 0)]} }
            ],
            'coordination_ring': [
                {   "h_loc": (1, 2),     "r_loc": (2, 1),    "objects": { "dish": [(2, 0)],               } },
                {   "h_loc": (1, 2),     "r_loc": (2, 1),    "objects": { "dish": [(2, 0), (1, 0), (0, 1)]} },
                {   "h_loc": (1, 2),     "r_loc": (3, 3),    "objects": { "dish": [(4, 3)],               } },
                {   "h_loc": (1, 2),     "r_loc": (3, 3),    "objects": { "dish": [(4, 3), (4, 2), (3, 4)]} }
            ],
            'bottleneck': [(4, 1)], # TODO: Finish this
            'room': [(1, 5)]
        }
        constants = {
            "h_held": lambda h_loc: ObjectState("onion", h_loc),
            "h_orientation_fn": lambda: Direction.SOUTH,
            "r_held": lambda r_loc: None,
            "r_orientation_fn": lambda: Direction.random_direction(),
            "objects": { loc : make_ready_soup_at_loc(loc) for loc in self.mdp.get_pot_locations() }
        }
        return InitialStatesCreator(initial_states_params, constants, self.mdp).get_initial_states()

    def setup_human_model(self):
        return StayAgent()

    def is_success(self, initial_state, final_state):
        trained_agent = final_state.players[1]
        r_has_dish = trained_agent.has_object() and trained_agent.get_object().name == 'dish'
        # To change, soups must have either moved from the pot (picked up), delivered, or created (which is hard as all pots are already full)
        soups_have_changed = initial_state.all_objects_by_type['soup'] != final_state.all_objects_by_type['soup']
        success = r_has_dish or soups_have_changed
        if success and self.print_info:
            print('PPO has object, or the pot state has changed --> success!')
        return success
        

############
# TEST 1Bi #
############


class Test1bi(AbstractRobustnessTest):
    """
    Interacting with counters -> Drop objects onto counter -> R holding the wrong object

    Test: R is holding the wrong object, and must drop it
    Details:Two variants:
                A) R has D when O needed (both pots empty)
                B) R has O when two Ds needed (both pots cooked)
            For both A and B:
                Starting locations in STPs
                Other player (H) is the median TOM
                H has nothing
    """

    test_types = ["state_robustness"] # TODO: actually check this, currently placeholder

    def get_initial_states(self):
        initial_states_params = {
            'coordination_ring': [
                # top-R / bottom-L:
                {   "h_loc": (3, 2),     "r_loc": (3, 1) },
                {   "h_loc": (2, 1),     "r_loc": (3, 1) },
                {   "h_loc": (1, 1),     "r_loc": (1, 3) },
                {   "h_loc": (3, 3),     "r_loc": (1, 3) },
                # Both near dish/soup:
                {   "h_loc": (3, 3),     "r_loc": (1, 2) },
                {   "h_loc": (1, 1),     "r_loc": (2, 3) },
                # Diagonal:
                {   "h_loc": (3, 3),     "r_loc": (1, 1) },
                {   "h_loc": (1, 1),     "r_loc": (3, 3) }
            ],
        }
        constants_variant_A = {
            "h_held": lambda h_loc: None,
            "h_orientation_fn": lambda: Direction.random_direction(),
            "r_held": lambda r_loc: ObjectState("dish", r_loc),
            "r_orientation_fn": lambda: Direction.random_direction(),
            "objects": {}
        }

        constants_variant_B = {
            "h_held": lambda h_loc: None,
            "h_orientation_fn": lambda: Direction.random_direction(),
            "r_held": lambda r_loc: ObjectState("onion", r_loc),
            "r_orientation_fn": lambda: Direction.random_direction(),
            "objects": { loc : make_ready_soup_at_loc(loc) for loc in self.mdp.get_pot_locations() }
        }

        variant_A_states = InitialStatesCreator(initial_states_params, constants_variant_A, self.mdp).get_initial_states()
        variant_B_states = InitialStatesCreator(initial_states_params, constants_variant_B, self.mdp).get_initial_states()
        return variant_A_states + variant_B_states

    def setup_human_model(self):
        return make_median_tom_agent(self.mdp)

    def is_success(self, initial_state, final_state):
        trained_agent_initial_state = initial_state.players[1]
        initial_object = trained_agent_initial_state.get_object().name
        trained_agent_final_state = final_state.players[1]
        # Agent must have gotten rid of initial object
        success = not (trained_agent_final_state.has_object() and trained_agent_final_state.get_object().name == initial_object)
        if success and self.print_info:
            print('PPO no longer has the {} --> success!'.format(initial_object))
        return success


#####################
# AGENT SETUP UTILS #
#####################

def setup_agents_to_evaluate(mdp, agent_type, agent_run_name, agent_seeds, agent_save_location):
    assert agent_save_location == "local", "Currently anything else is unsupported"

    if agent_type != "ppo":
        assert agent_seeds is None, "For all agent types except ppo agents, agent_seeds should be None"

    if agent_type == "ppo":
        seeds = get_ppo_run_seeds(agent_run_name) if agent_seeds is None else agent_seeds
        agents = []
        for seed in seeds:
            ppo_agent_base_path = PPO_DATA_DIR + agent_run_name + "/"
            agent, _ = get_ppo_agent(ppo_agent_base_path, seed=seed)
            agents.append(agent)
    elif agent_type == "bc":
        raise [get_bc_agent(agent_run_name)]
    elif agent_type == "tom":
        agents = [make_median_tom_agent(mdp)]
    elif agent_type == "opt_tom":
        raise NotImplementedError("need to implement this")
    elif agent_type == "rnd":
        agents = [RandomAgent()]
    else:
        raise ValueError("Unrecognized agent type")

    assert len(agents) > 0
    return agents

def get_bc_agent(agent_run_name):
    """Return the BC agent for this layout and seed"""
    raise NotImplementedError("Should port over code from ppo_pop to ensure that the BC agent used is the same as the one used for PPO_BC_1 training")
    bc_agent, _ = get_bc_agent_from_saved(agent_run_name, unblock_if_stuck=True, stochastic=True, overwrite_bc_save_dir=None)
    return bc_agent


##################
# MAKE TOM UTILS #
##################

def make_test_tom(mdp):
    # TODO: Not sure what type of agent this is supposed to be - OPT?
    mlp = make_mlp(mdp)
    test_agent = make_test_tom_agent(mdp.layout_name, mlp, tom_num=test_agent[3])
    print('Setting prob_pausing = 0')
    test_agent.prob_pausing = 0

def make_median_tom_agent(mdp):
    """Make the Median TOM agent -- with params such that is has the median score with other manual param TOMs"""
    mlp = make_mlp(mdp)
    _, alternate_names_params, _ = import_manual_tom_params(mdp.layout_name, 1)
    return ToMModel.from_alternate_names_params_dict(mlp, alternate_names_params[0])

def make_test_tom_agent(mdp, tom_num):
    # TODO: What is this?
    """Make a TOM from the VAL OR TRAIN? set used for ppo"""
    mlp = make_mlp(mdp)
    VAL_TOM_PARAMS, TRAIN_TOM_PARAMS, _ = import_manual_tom_params(mdp.layout_name, 20)
    tom_agent = make_tom_agent(mlp)
    tom_agent.set_tom_params(None, None, TRAIN_TOM_PARAMS, tom_params_choice=int(tom_num))
    return tom_agent


#####################
# MAIN TEST RUNNING #
#####################

all_tests = [Test1ai, Test1bi]

def run_tests(tests_to_run, layout, num_avg, agent_type, agent_run_name, agent_save_location, agent_seeds, print_info, display_runs):

    # Make all randomness deterministic
    set_global_seed(0)

    # Set up agent to evaluate
    mdp = make_mdp(layout)
    agents_to_eval = setup_agents_to_evaluate(mdp, agent_type, agent_run_name, agent_seeds, agent_save_location)

    tests = {}
    for test_class in all_tests:
        results_across_seeds = []

        for agent_to_eval in agents_to_eval:
            test_object = test_class(mdp, "medium", trained_agent=agent_to_eval, trained_agent_type=agent_type, agent_run_name=agent_run_name, num_rollouts_per_initial_state=num_avg, print_info=print_info, display_runs=display_runs)
            results_across_seeds.append(test_object.to_dict())

        tests[test_object.__class__.__name__] = aggregate_test_results_across_seeds(results_across_seeds)

    # TODO: once we have these objects, we can easily apply filtering on all the data to generate
    # test-type specific plots and so on.

    print("Test results", tests)

    return tests

def aggregate_test_results_across_seeds(results):
    for result_dict in results:
        for k, v in result_dict.items():
            if k != "success_rate":
                # All dict entries across seeds should be the same except for the success rate
                assert v == results[0][k]

    final_dict = copy.deepcopy(results[0])
    del final_dict["success_rate"]
    final_dict["success_rate_mean_and_se"] = mean_and_std_err([result["success_rate"] for result in results])
    return final_dict


#####################################
# SETUP AND RESULT PROCESSING UTILS #
#####################################

def make_mdp(layout):
    # Make the standard mdp for this layout:
    mdp = OvercookedGridworld.from_layout_name(layout, start_order_list=['any'] * 100, cook_time=20,
                                               rew_shaping_params=None)
    return mdp

def make_mlp(mdp):
    no_counters_params['counter_drop'] = mdp.get_counter_locations()
    no_counters_params['counter_goals'] = mdp.get_counter_locations()
    return MediumLevelPlanner.from_pickle_or_compute(mdp, no_counters_params, force_compute=False)



if __name__ == "__main__":
    """
    Run a qualitative experiment to test robustness of a trained agent. This code works through a suite of tests,
    largely involving putting the test-subject-agent in a specific state, with a specific other player, then seeing if 
    they can still play Overcooked from that position.
    """
    parser = ArgumentParser()
    parser.add_argument("-t", "--tests_to_run", default="all")
    parser.add_argument("-l", "--layout", help="layout", required=True)
    parser.add_argument("-n", "--num_avg", type=int, required=False, default=1)
    parser.add_argument("-a_t", "--agent_type", type=str, required=True, default="ppo") # Must be one of ["ppo", "bc", "tom", "opt_tom"]
    parser.add_argument("-a_n", "--agent_run_name", type=str, required=False, help='e.g. lstm_expt_cc0')
    parser.add_argument("-a_s", "--agent_seeds", type=str, required=False, help='[9999, 8888]')
    parser.add_argument("-r", "--agent_save_location", required=False, type=str, help="e.g. server or local", default='local') # NOTE: removed support for this temporarily
    parser.add_argument("-pr", "--print_info", default=False, action='store_true')
    parser.add_argument("-dr", "--display_runs", default=False, action='store_true')

    args = parser.parse_args()
    run_tests(**args.__dict__)




############
# OLD CODE #
############


    # results = []

    # for i, run_name in enumerate(run_names):

    #     for seed in seeds[i]:

    #         print('\n' + run_name + ' >> seed_' + str(seed))
    #         time0 = time.perf_counter()
    #         results.append()
    #         print('Time for this agent: {}'.format(time.perf_counter() - time0))

    # """POST PROCESSING..."""
    # # avg_dict = make_average_dict(run_names, results, bests, seeds)
    # # if final_plot is True:
    # #     plot_results(avg_dict, shorten)
    # # weighted_avg_dic = make_plot_weighted_avg_dict(run_names, results, bests, seeds)
    # # # save_results(avg_dict, weighted_avg_dic, results, run_folder, layout)
    # # print('\nFinal average dict: {}'.format(avg_dict))
    # # print('\nFinal wegihted avg: {}'.format(weighted_avg_dic))
    # print('\nFinal "results": {}'.format(results))


# def plot_results(avg_dict, shorten=False):
#
#     y_pos = np.arange(len(avg_dict.keys()))
#     colour = ['B' if i % 2 == 0 else 'R' for i in range(12)]
#     plt.bar(y_pos, avg_dict.values(), align='center', alpha=0.5, color=colour)
#     avg_dict_keys = [list(avg_dict.keys())[i][0:6] for i in range(len(avg_dict))] if shorten else list(avg_dict.keys())
#     plt.xticks(y_pos, avg_dict_keys, rotation=30)
#     plt.ylabel('Avg % success')
#     # plt.title('')
#     plt.show()

def make_average_dict(run_names, results, bests, seeds):
    i = 0
    avg_dict = {}
    for j, run_name in enumerate(run_names):
        for seed in seeds[j]:
            for best in bests:
                b = 'V' if best == 'val' else 'T'
                this_avg = np.mean([results[i][j] for j in range(len(results[i])) if results[i][j] != None])
                avg_dict['{}_{}_{}'.format(run_name, b, seed)] = this_avg
                i += 1
    return avg_dict

# def make_plot_weighted_avg_dict(run_names, results, bests, seeds):
#     i = 0
#     weighted_avg_dict = {}
#     weighting = [0] + [2] * 3 + [1] * 2 + [0] * 2 + [1] * 2  # Give extra weight to tests 1-3 because each has many more sub-tests than the rest, and it would've made sense to split them up
#     for j, run_name in enumerate(run_names):
#         for seed in seeds[j]:
#             for best in bests:
#                 b = 'V' if best == 'val' else 'T'
#                 this_avg = np.sum([results[i][k]*weighting[k] for k in range(len(results[i])) if results[i][k] != None]) \
#                                             / np.sum(weighting)
#                 weighted_avg_dict['{}_{}_{}'.format(run_name, b, seed)] = this_avg
#                 i += 1
#     # plot_results(weighted_avg_dict, shorten=True)
#     return weighted_avg_dict

def make_average_results(results):
    avg_results = []
    for i in range(results):
        this_avg = np.mean([results[i][j] for j in range(len(results[i])) if results[i][j] != None])
        avg_results.append(this_avg)
    return avg_results

def save_results(avg_dict, weighted_avg_dict, results, run_folder, layout):
    timestamp = time.strftime('%Y_%m_%d-%H_%M_%S_')
    filename = DATA_DIR + 'qualitative_expts/{}_avg_dict_{}_{}.txt'.format(run_folder, layout, timestamp)
    with open(filename, 'w') as json_file:
        json.dump(avg_dict, json_file)
    filename = DATA_DIR + 'qualitative_expts/{}_weighted_avg_dict_{}_{}.txt'.format(run_folder, layout, timestamp)
    with open(filename, 'w') as json_file:
        json.dump(weighted_avg_dict, json_file)
    filename = DATA_DIR + 'qualitative_expts/{}_results_{}_{}.txt'.format(run_folder, layout, timestamp)
    with open(filename, 'w') as json_file:
        json.dump(results, json_file)

def get_bc_agent(seed, layout, mdp, run_on):
    """Return the BC agent for this layout and seed"""
    bc_name = layout + "_bc_train_seed{}".format(seed)
    if run_on == 'local':
        BC_LOCAL_DIR = '/home/pmzpk/bc_runs/'
    bc_agent, _ = get_bc_agent_from_saved(bc_name, unblock_if_stuck=True,
                                           stochastic=True,
                                           overwrite_bc_save_dir=BC_LOCAL_DIR)
    bc_agent.set_mdp(mdp)
    return bc_agent

def get_run_info(agent_from):
    """Return the seeds and run_names for the run in run_folder"""

    # -------- Choose agents ---------
    if agent_from == 'lstm_expt_cc0':
        run_folder = agent_from
        run_names = ['cc_1tom', 'cc_20tom', 'cc_1bc', 'cc_20bc']
        seeds = [[3264, 4859, 9225]] * 4

    elif agent_from == 'lstm_agent_cring_1tom_seed2732':
        run_folder = agent_from
        run_names = ["ok"]
        seeds = [[2732]] #TODO why is seeds a list of lists?

    # if agent_from == 'toms':
    #     num_toms = 20
    #     run_names = ['tom{}'.format(i) for i in range(num_toms)]
    #     seeds, bests, shorten, run_folder = [[None]]*num_toms, [None], False, ''
    #
    # elif agent_from == 'bc':
    #     run_names = ['bc']
    #     bests, shorten, run_folder = [None], False, ''
    #     seeds = [[8502, 7786, 9094, 7709]]  # , 103, 5048, 630, 7900, 5309, 8417, 862, 6459, 3459, 1047, 3759, 3806, 8413, 790, 7974, 9845]]  # BCs from ppo_pop

    return run_folder, run_names, seeds


def return_agent_dir(run_on, run_folder):
    """Return the DIR where the agents are saved"""
    if run_on == 'server0':
        return '/home/paul/research/human_ai_robustness/human_ai_robustness/data/ppo_runs/' + run_folder
    elif run_on == 'server1':
        return '/home/paul/agents_to_QT/' + run_folder
    if run_on == 'server_az':
        return '/home/paul/human_ai_robustness/human_ai_robustness/data/ppo_runs/' + run_folder
    elif run_on == 'local':
        return '/Users/micah/Downloads/' + run_folder
        # return '/home/pmzpk/Documents/hr_coordination_from_server_ONEDRIVE/' + run_folder \
        #     if agent_from != 'toms' else ''

def get_agent_to_test(agent_from, run_name, seed, layout, mdp, run_on):
    """Return the agent that will undergo the qualitative tests"""
    if agent_from == 'toms':
        # The TOM agents are made within run_tests
        return run_name
    elif agent_from == 'bc':
        return get_bc_agent(seed, layout, mdp, run_on)
    else:
        return get_ppo_agent(EXPT_DIR, seed, best='train')[0]


# def make_cc_standard_test_positions():
#     # Make the standard_test_positions for this layout:
#     standard_test_positions = []
#     # Middle positions:
#     standard_test_positions.append({'r_loc': (3, 1), 'h_loc': (4, 1)})
#     standard_test_positions.append({'r_loc': (4, 1), 'h_loc': (3, 1)})
#     standard_test_positions.append({'r_loc': (3, 1), 'h_loc': (3, 3)})
#     standard_test_positions.append({'r_loc': (3, 3), 'h_loc': (3, 1)})
#     # Side positions:
#     standard_test_positions.append({'r_loc': (1, 1), 'h_loc': (1, 3)})
#     standard_test_positions.append({'r_loc': (1, 3), 'h_loc': (1, 1)})
#     standard_test_positions.append({'r_loc': (6, 1), 'h_loc': (6, 3)})
#     standard_test_positions.append({'r_loc': (6, 3), 'h_loc': (6, 1)})
#     # Diagonal positions:
#     standard_test_positions.append({'r_loc': (1, 1), 'h_loc': (6, 3)})
#     standard_test_positions.append({'r_loc': (6, 3), 'h_loc': (1, 1)})
#     standard_test_positions.append({'r_loc': (1, 3), 'h_loc': (6, 1)})
#     standard_test_positions.append({'r_loc': (6, 1), 'h_loc': (1, 3)})
#     return standard_test_positions
#
# def make_cring_standard_test_positions():
#     # Make the standard_test_positions for CRING:
#     standard_test_positions = []
#     # top-R / bottom-L:
#     standard_test_positions.append({'r_loc': (3, 1), 'h_loc': (3, 2)})
#     standard_test_positions.append({'r_loc': (3, 1), 'h_loc': (2, 1)})
#     standard_test_positions.append({'r_loc': (1, 3), 'h_loc': (1, 1)})
#     standard_test_positions.append({'r_loc': (1, 3), 'h_loc': (3, 3)})
#     # Both near dish/soup:
#     standard_test_positions.append({'r_loc': (1, 2), 'h_loc': (3, 3)})
#     standard_test_positions.append({'r_loc': (2, 3), 'h_loc': (1, 1)})
#     # Diagonal:
#     standard_test_positions.append({'r_loc': (1, 1), 'h_loc': (3, 3)})
#     standard_test_positions.append({'r_loc': (3, 3), 'h_loc': (1, 1)})
#     return standard_test_positions



    # "OPTIMAL" TOM AGENT SETTINGS:
    # print('>>> Manually overwriting the TOM with an "optimal" TOM <<<')
    # tom_agent.prob_greedy = 1
    # tom_agent.prob_pausing = 0
    # tom_agent.prob_random_action = 0
    # tom_agent.rationality_coefficient = 20
    # tom_agent.path_teamwork = 1
    # tom_agent.prob_obs_other = 0
    # tom_agent.wrong_decisions = 0
    # tom_agent.prob_thinking_not_moving = 0
    # tom_agent.look_ahead_steps = 4
    # tom_agent.retain_goals = 0
    # tom_agent.compliance = 0

    

# def make_default_test_dict():
#     return dict.fromkeys("type", "description", "number", "layouts", "score",
#             "robustness_to_states",  # Whether this test is testing robustness to (potentially unseen) states
#             "robustness_to_agents",  # Whether this test is testing robustness to unseen
#             "memory",  # Is it testing memory
#             "testing_other"
#                          )





# h_locs_by_layout = {
    #     'counter_circuit': [(1, 2)],
    #     'coordination_ring': [(1, 2)],
    #     'bottleneck': [(4, 1)],
    #     'room': [(1, 5)]
    # }
    # r_locs_by_layout = {
    #     'counter_circuit': [
    #         (1, 1), 
    #         (6, 1)
    #     ],
    #     'coordination_ring': [
    #         (2, 1), 
    #         (3, 3)
    #     ],
    #     'bottleneck': [(5, 1), (1, 1)],
    #     'room': [(2, 4), (4, 1)]
    # }
    # object_locations_by_layout = {
    #     'dish': {
    #         'counter_circuit': [
    #             [(0, 1)],
    #             [(0, 1), (1, 0), (6, 0)]
    #         ],
    #         'coordination_ring': [
    #             [(0, 1)],
    #             [(0, 1), (1, 0), (6, 0)]
    #         ],
    #         'bottleneck': [
    #             [(0, 1)],
    #             [(0, 1), (1, 0), (6, 0)]
    #         ],
    #         'room': [
    #             [(0, 1)],
    #             [(0, 1), (1, 0), (6, 0)]
    #         ]
    #     }
    # }




# def run_test_1ai(test_agent, mdp, print_info, stationary_tom_agent, layout, display_runs):
#     """1ai) Pick up a dish from a counter: H blocks dispenser (in layouts with only one dispenser)
#     Details:    4 different settings for R's location and the location of the dishes
#                 Both pots cooking
#                 H holding onion facing South; R holding nothing
#                 Success: R gets a dish or changes the pot state?

#                 POSSIBLE ADDITIONS: Give H no object. More positions for R.
#     """

#     other_player = stationary_tom_agent
#     orientations = [(1, 0), (0, 1), (-1, 0), (0, -1)]
#     first_pot_loc, second_pot_loc = mdp.get_pot_locations()
#     count_success = 0
#     num_tests = 0
#     subtest_successes = []
#     pots = [ObjectState('soup', first_pot_loc, ('onion', 3, 20)), ObjectState('soup', second_pot_loc, ('onion', 3, 20))] # Both cooking
#     h_locs_layout = {'counter_circuit': (1, 2), 'coordination_ring': (1, 2), 'bottleneck': (4, 1), 'room': (1, 5)}
#     h_loc = h_locs_layout[layout]
#     tom_player_state = PlayerState(h_loc, (0, 1), held_object=ObjectState('onion', h_loc))

#     r_d_locations_list = get_r_d_locations_list_1ai(layout)

#     for i, r_d_locations in enumerate(r_d_locations_list):

#         num_tests += 1
#         if print_info:
#             print('\nR and Dish locations: {}\n'.format(r_d_locations))

#         # Arbitrarily but deterministically choose R's orientation:
#         ppo_or = Direction.ALL_DIRECTIONS[(i+1) % 4]

#         # Make the overcooked state:
#         ppo_player_state = PlayerState(r_d_locations['r_loc'], ppo_or, held_object=None)

#         dish_states = [ObjectState('dish', r_d_locations['d_locs'][k]) for k in range(len(r_d_locations['d_locs']))]
#         objects_dict = {pots[k].position: pots[k] for k in range(len(pots))}
#         objects_dict.update({dish_states[k].position: dish_states[k] for k in range(len(r_d_locations['d_locs']))})

#         state_i = OvercookedState(players=[ppo_player_state, tom_player_state], objects=objects_dict,
#                                     order_list=['any']*100)  # players: List of PlayerStates (order corresponds to player indices). objects: Dictionary mapping positions (x, y) to ObjectStates.
#         # Check it's a valid state:
#         mdp._check_valid_state(state_i)

#         env = OvercookedEnv(mdp, start_state_fn=lambda : state_i)
#         env.horizon = get_layout_horizon(layout, "medium", test_agent)

#         # Play with the tom agent from this state and record score
#         agent_pair = AgentPair(test_agent, other_player)
#         trajs = env.get_rollouts(agent_pair, num_games=1, final_state=True, display=display_runs, info=False)

#         # Score in terms of whether the pot state changes:
#         state_f = trajs["ep_observations"][0][-1]
#         env.state = state_f
#         if print_info:
#             print('\nInitial state:\n{}'.format(OvercookedEnv(mdp, start_state_fn=lambda: state_i)))
#             print('\nFinal state:\n{}'.format(env))

#         if (state_f.players[0].has_object() and state_f.players[0].get_object().name == 'dish') or \
#                 state_i.all_objects_by_type['soup'] != state_f.all_objects_by_type['soup']:
#             if print_info:
#                 print('PPO has object, or the pot state has changed --> success!')
#             count_success += 1
#             subtest_successes.append('S')
#         else:
#             subtest_successes.append('F')

#         if print_info:
#             print(count_success/num_tests)
#             print('Subtest successes: {}'.format(subtest_successes))

#     score = count_success/num_tests
#     return score


# def get_r_d_locations_list_1ai(layout):
#     """R and Dish locations for test 1ai
#     2 R locs near the dish. 2 far away
#     Both with one dish and with lots of dishes"""
#     if layout == 'counter_circuit':
#         return [{'r_loc': (1, 1), 'd_locs': [(0, 1)]},
#                 {'r_loc': (1, 1), 'd_locs': [(0, 1), (1, 0), (6, 0)]},
#                 {'r_loc': (6, 1), 'd_locs': [(6, 0)]},
#                 {'r_loc': (6, 1), 'd_locs': [(0, 1), (1, 0), (6, 0)]}]
#     elif layout == 'coordination_ring':
#         return [{'r_loc': (2, 1), 'd_locs': [(2, 0)]},
#                 {'r_loc': (2, 1), 'd_locs': [(2, 0), (1, 0), (0, 1)]},
#                 {'r_loc': (3, 3), 'd_locs': [(4, 3)]},
#                 {'r_loc': (3, 3), 'd_locs': [(4, 3), (4, 2), (3, 4)]}]
#     elif layout == 'bottleneck':
#         return [{'r_loc': (5, 1), 'd_locs': [(6, 1)]},
#                 {'r_loc': (5, 1), 'd_locs': [(6, 1), (5, 0), (3, 2)]},
#                 {'r_loc': (1, 1), 'd_locs': [(0, 1)]},
#                 {'r_loc': (1, 1), 'd_locs': [(0, 1), (1, 0), (0, 2)]}]
#     elif layout == 'room':
#         return [{'r_loc': (2, 4), 'd_locs': [(0, 4)]},
#                 {'r_loc': (2, 4), 'd_locs': [(0, 4), (2, 6), (3, 6)]},
#                 {'r_loc': (4, 1), 'd_locs': [(4, 0)]},
#                 {'r_loc': (4, 1), 'd_locs': [(4, 0), (5, 0), (6, 2)]}]
#     elif layout == 'centre_pots':
#         return None
#     elif layout == 'centre_objects':
#         return None


# def run_tests(layout, test_agent, tests_to_run, print_info, num_avg, mdp, mlp, display_runs, agent_name):
#     """..."""

#     # Make TOM test agent:
#     if test_agent.__class__ is str and test_agent[:3] == 'tom':
#         test_agent = make_test_tom_agent(layout, mlp, tom_num=test_agent[3])
#         print('Setting prob_pausing = 0')
#         test_agent.prob_pausing = 0

#     # Make the TOM agents used for testing:
#     # stationary_tom_agent = ToMModel.get_stationary_ToM(mlp) #TODO: Can't we just use a StayAgent?
#     stationary_tom_agent = StayAgent() # 
#     median_tom_agent = make_median_tom_agent(mlp, layout)
#     # random_tom_agent = make_random_tom_agent(mlp, layout) # TODO: Can't we just use a RandomAgent?
#     random_tom_agent = RandomAgent() 
    

#     # if layout == 'counter_circuit':
#     #     standard_test_positions = make_cc_standard_test_positions()
#     # elif layout == 'coordination_ring':
#     #     standard_test_positions = make_cring_standard_test_positions()

#     results_this_agent = []



#     # Test 1ai:
#     test_metadata = {
#         'type': '1) Interacting with counters',
#         'description': 'Pick up a dish from a counter; H blocks dispenser (valid for layouts with one blockable dispenser)',
#         'number': '1ai',
#         'layouts': ['bottleneck', 'room', 'coordination_ring', 'counter_circuit'],
#         # TODO: None means "not sure if True or False"!
#         'robustness_to_states': None,  # Whether this test is testing robustness to (potentially unseen) states
#         'robustness_to_agents': None,  # Whether this test is testing robustness to unseen
#         'testing_other': ['reacting_to_other_agent', 'off_distribution_game_state']
#     }
#     # If this test isn't valid for this layout, then give a score of None,
#     test_score = run_test_1ai(test_agent, mdp, print_info, stationary_tom_agent, display_runs)
#     results_this_agent.append(
#         (test_score, test_metadata)
#     )





#     results_dict_this_agent = {agent_name: results_this_agent}


#     # percent_success = [None]*10
#     #
#     # if "1" in tests_to_run or tests_to_run == "all":
#     #     # TEST 1: "H stands still with X, where X CANNOT currently be used"
#     #     count_successes = []
#     #     for _ in range(num_avg):
#     #         count_success, num_tests = h_random_unusable_object(test_agent, mdp, standard_test_positions,
#     #                                                             print_info, random_tom_agent, layout, display_runs)
#     #         count_successes.append(count_success)
#     #     percent_success[1] = round(100 * np.mean(count_successes) / num_tests)
#     #     # num_tests_all[1] = num_tests

#     # print('RESULT: {}'.format(?))
#     return results_this_agent





# OLD

# def make_random_tom_agent(mlp, layout):
#     """Make a random TOM agent -- takes random actions"""
#     compliance, teamwork, retain_goals, wrong_decisions, prob_thinking_not_moving, path_teamwork, \
#     rationality_coefficient, prob_pausing, prob_greedy, prob_obs_other, look_ahead_steps = [99] * 11
#     tom_agent = ToMModel(mlp=mlp, prob_random_action=0, compliance=compliance, teamwork=teamwork,
#                          retain_goals=retain_goals, wrong_decisions=wrong_decisions,
#                          prob_thinking_not_moving=prob_thinking_not_moving, path_teamwork=path_teamwork,
#                          rationality_coefficient=rationality_coefficient, prob_pausing=prob_pausing,
#                          use_OLD_ml_action=False, prob_greedy=prob_greedy, prob_obs_other=prob_obs_other,
#                          look_ahead_steps=look_ahead_steps)
#     _, TOM_PARAMS, _ = import_manual_tom_params(layout, 1)
#     tom_agent.set_tom_params(None, None, TOM_PARAMS, tom_params_choice=0)
#     # Then make it take random steps (set both, just to be sure):
#     tom_agent.rationality_coefficient = 0.01
#     tom_agent.prob_random_action = 1
#     return tom_agent