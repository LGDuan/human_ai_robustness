CUDA_VISIBLE_DEVICES=0 python qualitative_robustness_expt.py -l counter_circuit -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=1 python qualitative_robustness_expt.py -l coordination_ring -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=2 python qualitative_robustness_expt.py -l counter_circuit -a_t teamworky_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=3 python qualitative_robustness_expt.py -l coordination_ring -a_t teamworky_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=2 python qualitative_robustness_expt.py -l bottleneck -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=3 python qualitative_robustness_expt.py -l large_room -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=0 python qualitative_robustness_expt.py -l centre_objects -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=1 python qualitative_robustness_expt.py -l centre_pots -a_t semigreedy_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=2 python qualitative_robustness_expt.py -l bottleneck -a_t teamworky_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=3 python qualitative_robustness_expt.py -l large_room -a_t teamworky_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=0 python qualitative_robustness_expt.py -l centre_objects -a_t teamworky_opt_tom -n 10 -nv 1
CUDA_VISIBLE_DEVICES=1 python qualitative_robustness_expt.py -l centre_pots -a_t teamworky_opt_tom -n 10 -nv 1
