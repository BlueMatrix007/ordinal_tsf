import os
import pandas as pd
import pickle
from ordinal_tsf.model import MordredStrategy
from ordinal_tsf.dataset import Dataset, Quantiser, Standardiser, WhiteCorrupter, AttractorStacker, Selector, TestDefinition
from ordinal_tsf.session import Session
from ordinal_tsf.util import cartesian
os.environ["CUDA_VISIBLE_DEVICES"]="7"

import tensorflow as tf
from keras.backend.tensorflow_backend import set_session
config = tf.ConfigProto()
config.gpu_options.per_process_gpu_memory_fraction = 0.45
set_session(tf.Session(config=config))


MAX_LENGTH = 30000
LOOKBACK = 100
HORIZON = 100
ATTRACTOR_LAG = 10
EFFECTIVE_LAG = 0
VALIDATION_PREDICTIVE_HORIZON = 500
TEST_PREDICTIVE_HORIZON = 1000
DECODER_SEED_LENGTH = 1
# open/create session (folder name) (includes raw time series loading)
# choose experiment (includes model preparation)
best_models = {}
mordred_search_space = {'lam': [1e-6, 1e-7, 1e-8],
                        'dropout_rate': [0.25, 0.5],
                        'units': [64, 128, 256, 320],
                        'lookback': [LOOKBACK],
                        'horizon': [HORIZON]}

train_spec = {'epochs': 50, 'batch_size': 256, 'validation_split': 0.15}
DS = 'mg'

sess = Session('{}'.format(DS))
VALIDATION_START_INDEX = LOOKBACK + 2 * ATTRACTOR_LAG + DECODER_SEED_LENGTH
TEST_START_INDEX = LOOKBACK + 2 * ATTRACTOR_LAG + DECODER_SEED_LENGTH

## Transformations to be applied to the dataset
x = pd.read_feather('WebTS/{}.feather'.format(DS)).values[:MAX_LENGTH]
stand = Standardiser()
quant = Quantiser()
white_noise = WhiteCorrupter()

dataset = Dataset(x, LOOKBACK + HORIZON + DECODER_SEED_LENGTH,
                  p_val=0.15, p_test=0.15, preprocessing_steps=[stand, quant])

mordred_search_space['ordinal_bins'] = [quant.n_bins]
mordred_search_space['n_channels'] = [dataset.optional_params.get('n_channels', 1)]


## Definition of validation tests to choose best hyperparameters
selector = Selector(VALIDATION_START_INDEX, VALIDATION_PREDICTIVE_HORIZON)
continuous_ground_truth = dataset.apply_partial_preprocessing('val', [selector, stand])
ordinal_ground_truth = dataset.apply_partial_preprocessing('val', [selector, stand, quant])

validation_tests = [TestDefinition('mse', continuous_ground_truth),
                    TestDefinition('nll', ordinal_ground_truth),
                    TestDefinition('cum_nll', ordinal_ground_truth),
                    TestDefinition('median_dtw_distance', continuous_ground_truth),
                    TestDefinition('median_attractor_distance', continuous_ground_truth)]

validation_plots = {'plot_median_2std': {'ground_truth':continuous_ground_truth},
                    'plot_cum_nll': {'binned_ground_truth': ordinal_ground_truth},
                    'plot_like': {}}

## Trains models and chooses best hyperparameters
experiment = sess.start_experiment(dataset, MordredStrategy)
best_models[DS] = experiment.choose_model(validation_tests,
                                          mordred_search_space.keys(),
                                          cartesian(mordred_search_space.values()),
                                          VALIDATION_START_INDEX - EFFECTIVE_LAG,
                                          VALIDATION_PREDICTIVE_HORIZON,
                                          plots=validation_plots,
                                          fit_kwargs=train_spec,
                                          eval_kwargs={'mc_samples': 50},
                                          mode='val')

## Tests on actual test data
selector = Selector(TEST_START_INDEX, TEST_PREDICTIVE_HORIZON)
continuous_ground_truth = dataset.apply_partial_preprocessing('test', [selector, stand])
ordinal_ground_truth = dataset.apply_partial_preprocessing('test', [selector, stand, quant])

final_tests = [TestDefinition('mse', continuous_ground_truth),
               TestDefinition('nll', ordinal_ground_truth),
               TestDefinition('cum_nll', ordinal_ground_truth),
               TestDefinition('median_dtw_distance', continuous_ground_truth),
               TestDefinition('median_attractor_distance', continuous_ground_truth)]

test_plots = {'plot_median_2std': {'ground_truth': continuous_ground_truth},
              'plot_median_dtw_alignment': {'ground_truth': continuous_ground_truth},
              'plot_cum_nll': {'binned_ground_truth': ordinal_ground_truth},
              'plot_like': {}}

for metric, best_model in best_models[DS].items():
    print 'Test result for model with best {} performance'.format(metric)
    experiment.choose_model(final_tests,
                            best_model.keys(),
                            [best_model.values()],
                            TEST_START_INDEX - EFFECTIVE_LAG,
                            TEST_PREDICTIVE_HORIZON,
                            plots=test_plots,
                            fit_kwargs=train_spec,
                            eval_kwargs={'mc_samples': 100},
                            mode='test')

with open('best_models_mordred', 'wb') as f:
    pickle.dump(best_models, f)

exit()
