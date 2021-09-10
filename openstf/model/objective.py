# SPDX-FileCopyrightText: 2017-2021 Alliander N.V. <korte.termijn.prognoses@alliander.com> # noqa E501>
#
# SPDX-License-Identifier: MPL-2.0
import optuna
from typing import Union, Tuple

import openstf
from openstf.model.regressors.regressor_interface import OpenstfRegressorInterface
from openstf.enums import MLModelType
from datetime import datetime, timedelta
from openstf.model_selection.model_selection import split_data_train_validation_test

EARLY_STOPPING_ROUNDS: int = 10
TEST_FRACTION: float = 0.1
VALIDATION_FRACTION: float = 0.1
# See https://xgboost.readthedocs.io/en/latest/parameter.html for all possibilities
EVAL_METRIC: str = "mae"


# https://optuna.readthedocs.io/en/stable/faq.html#objective-func-additional-args
class RegressorObjective:
    """Regressor optuna objective function.

    Use any of the derived classses for optimization using an optuna study.
    The constructor is used to set the "input_data" and optionally add some
    configuration. Next the instance will be called by he optuna study during
    optimization.

    Example:
        # initialize a (derived class) objective function
        objective = XGBRegressorObjective(input_data, test_fraction)
        # use the objective function
        study.optimize(objective)
    """

    def process_tuple(self, trial: optuna.trial.FrozenTrial, key: str, value: Tuple[Union[int, float], Union[int, float]]) -> \
    Union[int, float]:
        """ Pick hyperparameter for tuple  """
        tup, log = value
        startValue, endValue = tup

        error = "input values for the tuple can be float/float, float/int, int/float, int/int"

        if isinstance(startValue, float) or isinstance(endValue, float):
            return trial.suggest_float(key, float(startValue), float(endValue), log=log)

        elif isinstance(startValue, int) and isinstance(endValue, int):
            return trial.suggest_int(key, startValue, endValue)

        else:
            raise TypeError(error)

    def get_trial_parameters(self, model_params: dict, trial: optuna.trial.FrozenTrial) -> dict:
        """
        Pick hyperparameters from the hyperparameter space using optuna.
        The dictionary can contain 2 possible types: tuple or List
        1. a list can directly be used in the suggest_categorical
        2. For the tuple we need a check to see what the tuple contains
            a. two strings; it will pick one of the values based on the model used
            b. one float with one integer or two floats;
            will set the first value as lowerbound and the second value as upperbound and picks floats between those bounds.
            This uses the log boolean which is defined in the tuple
            c. two integers;
            will set the first value as lowerbound and the second value as upperbound and picks integers between those bounds.
            log boolean is ignored.

        """
        param = {}
        for key, value in model_params.items():
            # In the default parameter space we make use of tuples ((startValue: Union[int, float], endValue: Union[int, float]),log: bool)
            if isinstance(value, tuple):
                param[key] = self.process_tuple(trial, key, value)
            # If the parameter is a list it means it is a categorical feature
            elif isinstance(value, list):
                param[key] = trial.suggest_categorical(key, value)

            else:
                raise TypeError("Possible input values: tuple, list")

        return param

    def __init__(
        self,
        input_data,
        model: OpenstfRegressorInterface,
        pruning_function: optuna.integration,
        model_params: dict,
        start_time: datetime,
        test_fraction=TEST_FRACTION,
        validation_fraction=VALIDATION_FRACTION,
        eval_metric=EVAL_METRIC,
        verbose=False,
        **args_eval
    ):
        self.input_data = input_data
        self.model = model
        self.pruning_function = pruning_function
        self.model_params = model_params
        self.start_time = start_time
        self.test_fraction = test_fraction
        self.validation_fraction = validation_fraction
        self.eval_metric = eval_metric
        self.verbose = verbose
        self.args_eval = args_eval
        # Should be set on a derived classes
        self.model_type = None

    def __call__(self, trial: optuna.trial.FrozenTrial) -> float:
        """Optuna objective function.

        Args: trial

        Returns:
            float: Mean absolute error for this trial.
        """
        # Check elapsed time
        elapsed = datetime.utcnow() - self.start_time
        if elapsed > timedelta(minutes=2, seconds=0):
            trial.study.stop()

        # Perform data preprocessing
        train_data, validation_data, test_data = split_data_train_validation_test(
            self.input_data,
            test_fraction=self.test_fraction,
            validation_fraction=self.validation_fraction,
            backtest=True,
        )

        # Test if first column is "load" and last column is "horizon"
        if train_data.columns[0] != "load" or train_data.columns[-1] != "horizon":
            raise RuntimeError(
                "Column order in train input data not as expected, "
                "could not train a model!"
            )

        # Split in x, y data (x are the features, y is the load)
        train_x, train_y = train_data.iloc[:, 1:-1], train_data.iloc[:, 0]
        valid_x, valid_y = validation_data.iloc[:, 1:-1], validation_data.iloc[:, 0]
        test_x, test_y = test_data.iloc[:, 1:-1], test_data.iloc[:, 0]

        # Configure evals for early stopping
        eval_set = [(train_x, train_y), (valid_x, valid_y)]

        # get the parameters used in this trial
        param = self.get_trial_parameters(self.model_params, trial)

        # create the specific pruning callback
        pruning_callback = self.pruning_function(trial, **self.args_eval)

        # insert parameters into model
        self.model.set_params(**param)

        # validation_0 and validation_1 are available
        self.model.fit(
            train_x,
            train_y,
            eval_set=eval_set,
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            verbose=self.verbose,
            eval_metric=self.eval_metric,
            callbacks=[pruning_callback],
        )

        forecast_y = self.model.predict(test_x)

        try:
            loss = "openstf.metrics.metrics." + self.eval_metric
            metric = eval(loss)(test_y, forecast_y)
            return metric
        except AttributeError:
            print("loss function is not defined in openstf.metrics.metrics")

class XGBRegressorObjective(RegressorObjective):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_type = MLModelType.XGB

    def get_params(self, trial: optuna.trial.FrozenTrial) -> dict:
        params = {
            "eta": trial.suggest_float("eta", 0.01, 0.2),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 6),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "gamma": trial.suggest_float("gamma", 0.0, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        }
        return params
