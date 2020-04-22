
from human_aware_rl.ppo.ppo_pop import plot_ppo_tom

# SEEDS = [3264, 4859, 9225, 2732, 9845]
SEEDS = [2732]

DIR = '/home/pmzpk/Documents/hr_coordination_from_server_ONEDRIVE/hp_lstm_croom1'
# DIR = '/home/pmzpk/Dropbox/Pycharm_paulk444/human_ai_robustness/human_ai_robustness/data/'

# runs = ['tom_{}'.format(i) for i in range(12)]
# map = 'cc'
runs = ['2b', '2c', '3b', '3c', '1b', '7b', '7c', '12', '13', '5c']
map = 'croom'

for i in range(len(runs)):

    run_name = '{}_{}'.format(map, runs[i])
    # run_name = 'tom_pop_expt/cring_20_toms_p'

    plot_ppo_tom(DIR, run_name, SEEDS, plot_val=False)
