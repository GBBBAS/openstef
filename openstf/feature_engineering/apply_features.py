# SPDX-FileCopyrightText: 2017-2021 Alliander N.V. <korte.termijn.prognoses@alliander.com> # noqa E501>
#
# SPDX-License-Identifier: MPL-2.0

# -*- coding: utf-8 -*-
"""apply_features.py.

This module provides functionality for applying features to the input data.
This improves forecast accuracy. Examples of features that are added are:
    The load 1 day and 7 days ago at the same time
    If a day is a weekday or a holiday
    The extrapolated windspeed at 100m
    The normalised wind power according to the turbine-specific power curve

"""
import pandas as pd

from openstf.feature_engineering.holiday_features import (
    generate_holiday_feature_functions,
)
from openstf.feature_engineering.weather_features import (
    add_humidity_features,
    add_additional_wind_features,
)
from openstf.feature_engineering.lag_features import generate_lag_feature_functions


def apply_features(
    data: pd.DataFrame, features: list = None, horizon: float = 24.0
) -> pd.DataFrame:
    """This script applies the feature functions defined in
        feature_functions.py and returns the complete dataframe. Features requiring
        more recent label-data are omitted.

    Args:
        data (pandas.DataFrame): a pandas dataframe with input data in the form:
                                    pd.DataFrame(
                                        index=datetime,
                                        columns=[label, predictor_1,..., predictor_n]
                                    )
        features (list of strs): list of reuqested features
        horizon (float): Forecast horizon limit in hours.

    Returns:
        pd.DataFrame(index = datetime, columns = [label, predictor_1,..., predictor_n,
            feature_1, ..., feature_m])

    Example:
        import pandas as pd
        import numpy as np
        index = pd.date_range(start = "2017-01-01 09:00:00",
        freq = '15T', periods = 200)
        data = pd.DataFrame(index = index,
                            data = dict(load=
                            np.sin(index.hour/24*np.pi)*
                            np.random.uniform(0.7,1.7, 200)))

    """

    # Get lag feature functions
    feature_functions = generate_lag_feature_functions(features, horizon)

    # Get timedrivenfeature functions
    feature_functions.update(
        {
            "IsWeekendDay": lambda x: (x.index.weekday // 5) == 1,
            "IsWeekDay": lambda x: x.index.weekday < 5,
            "IsSunday": lambda x: x.index.weekday == 6,
            "Month": lambda x: x.index.month,
            "Quarter": lambda x: x.index.quarter,
        }
    )

    # Get holiday feature functions
    feature_functions.update(generate_holiday_feature_functions())

    # Don't generate feature is not in features
    if features is not None:
        # Add the features to the dataframe using previously defined feature functions
        for key, featfunc in feature_functions.items():
            if key not in features:
                continue
            data[key] = data.iloc[:, [0]].apply(featfunc)

    # Add additional wind features
    data = add_additional_wind_features(data, features)

    # Add humidity features
    data = add_humidity_features(data, features)

    # Return dataframe including all requested features
    return data
