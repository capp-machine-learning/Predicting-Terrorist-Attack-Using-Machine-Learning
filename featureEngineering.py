"""
Title:       Build a preprocessing pipeline that helps user preprocess training
             and test data from the corresponding CSV input files.

Description: Fill in missing values, discretize continuous variables, generate
             new features, deal with categorical variables with multiple levels,
             scale data, and save preprocessed data.

Author:      Kunyu He, CAPP'20, The University of Chicago

"""

import warnings

warnings.filterwarnings("ignore")

import argparse
import logging
import os
import re
import time

import numpy as np
import pandas as pd
from sklearn.externals import joblib
from sklearn.preprocessing import OrdinalEncoder, StandardScaler, MinMaxScaler

from viz import read_data

#----------------------------------------------------------------------------#
INPUT_DIR = "../data/"
OUTPUT_DIR = "../processed_data/"
LOG_DIR = "../logs/featureEngineering/"

DATA_FILE = "projects.csv"
TRAIN_FEATURES_FILE = 'train_features.txt'
TEST_FEATURES_FILE = 'test_features.txt'

# logging
logger= logging.getLogger('featureEngineering')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
logger.addHandler(ch)
fh = logging.FileHandler(LOG_DIR + time.strftime("%Y%m%d-%H%M%S") + '.log')
logger.addHandler(fh)

pd.set_option('mode.chained_assignment', None)
warnings.filterwarnings("ignore")


#----------------------------------------------------------------------------#
def ask(names, message):
    """
    Ask user for their choice of index for model or metrics.

    Inputs:
        - name (list of strings): name of choices
        - message (str): type of index to request from user

    Returns:
        (int) index for either model or metrics
    """
    indices = []

    print("\nUp till now we support:")
    for i, name in enumerate(names):
        print("%s. %s" % (i + 1, name))
        indices.append(str(i + 1))

    index = input("Please input a %s index:\n" % message)

    if index in indices:
        return int(index) - 1
    else:
        print("Input wrong. Type one in {} and hit Enter.".format(indices))
        return ask(names, message)


def temporal_split(data, var, test_length, gap):
    """
    Split the data into several train and test pairs with fixed-length test sets
    and variant-length training set. Training sets are all the observations up
    till the test sets plus gap (to give the results enough time to show up).
    The first training set is of the same length as the test sets.

    Inputs:
        - data (DataFrame) data matrix to be split it to training and test sets
        - var (string): split in terms of the column
        - test_length (string): length of the test set (e.x. 6M, 10D)
        - gap (string): length of the gap between training and test set, and
            after test set until the end

    Returns:
        (list of tuples of DataFrames) each tuple is a training and test pair

    """
    gap_delta = pd.Timedelta(int(re.findall(r'[0-9]+', gap)[0]),
                             re.findall(r'[a-zA-Z]+', gap)[0])
    test_delta = pd.Timedelta(int(re.findall(r'[0-9]+', test_length)[0]),
                              re.findall(r'[a-zA-Z]+', test_length)[0])
    pairs = []

    training_end = (data[var].min() + test_delta).date()
    test_start = training_end + gap_delta
    test_end = test_start + test_delta
    max_date = data[var].max().date() - gap_delta

    while test_end <= max_date:
        pairs.append((data[data[var] < training_end],
                      data[(data[var] >= test_start) & (data[var] < test_end)]))

        test_start = test_end
        test_end += test_delta
        training_end = test_start - gap_delta

    logger.info(("Using a test length of '%s', with a '%s' gap between "
                 "training and test sets, and at the end of the data set "
                 "observations of the last '%s' cannot be used for either "
                 "training or testing.") % (test_length, gap, gap))
    logger.info(("Print the start and end date for each of the %s pairs of "
                 "training and test sets to verify the split works.\n") %
                len(pairs))
    for i, (train, test) in enumerate(pairs):
        messages = ["<TRAINING-TEST PAIR %s>\n" % i,
                    "<TRAINING SET TIME RANGE> %s - %s" %
                    (train[var].min().date(), train[var].max().date()),
                    "<TEST SET TIME RANGE> %s - %s" %
                    (test[var].min().date(), test[var].max().date())]
        dir_path = OUTPUT_DIR + ("Batch %s/" % i)
        create_dirs(dir_path)
        with open(dir_path + "time_window.txt", 'w') as file:
            file.write(",".join(messages))

        for message in messages:
            logger.info(message)
        logger.info("\n\n")
    logger.info("All time windows wrote to sub-directories under %s.\n" %
                OUTPUT_DIR)

    return pairs


def read_feature_names(dir_path, file_name):
    """
    Read .txt files with only one line as feature names separated by ",". Save
    the output to a list of feature names.

    Returns:
        (list of strings) list of feature names.
    """
    with open(dir_path + file_name, 'r') as handle:
        return np.array(handle.readline().split(","))


def create_dirs(dir_path):
    """
    Create a new directory if it doesn't exist and add a '.gitkeep' file to the
    directory.

    """
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        file = open(dir_path + ".gitkeep", "w+")
        file.close()


class FeaturePipeLine:
    """
    Preprocess pipeline for a data set from CSV file. Modify the class
    variables to fill in missing values, combine multinomial variables to ones
    with less levels and binaries, and apply one-hot-encoding. Then split data
    into features and target, drop rows with missing labels and some columns.
    At last, apply scaling.

    """
    TO_FILL_CON = {'students_reached'}

    TO_FILL_OBJ = {'school_metro': None,
                   'school_district': "MISC",
                   'primary_focus_subject': "Other",
                   'primary_focus_area': "Other",
                   'secondary_focus_subject': "MISC",
                   'secondary_focus_area': "MISC",
                   'resource_type': None}

    TO_DISCRETIZE = {'total_price_including_optional_support': (True, 5, 0),
                     'students_reached': (True, 5, 0),
                     'school_longitude': (False, 8, 3),
                     'school_latitude': (False, 3, 3)}

    TO_COMBINE = {'teacher_prefix': {"Mr.": ["Dr."]},
                  'school_city': {"MISC": None},
                  'school_state': {"MISC": None},
                  'school_district': {"MISC": None},
                  'school_county': {"MISC": None},
                  'primary_focus_subject': {"Other": None},
                  'primary_focus_area': {"Other": None},
                  'secondary_focus_subject': {"Other": None},
                  'secondary_focus_area': {"Other": None},
                  'resource_type': {"Other": None}}

    TO_BINARIES = {'school_charter': 'auto',
                   'school_magnet': 'auto',
                   'eligible_double_your_impact_match': 'auto'}

    TO_EXTRACT_DATE_TIME = {'date_posted': ["year", "month"]}

    TO_ONE_HOT = ['school_city', 'school_state', 'school_district',
                  'school_county', 'school_metro', 'teacher_prefix',
                  'primary_focus_subject', 'primary_focus_area',
                  'secondary_focus_subject', 'secondary_focus_area',
                  'resource_type', 'poverty_level', 'grade_level']

    TARGET = 'fully_funded'
    TO_DROP = ['projectid', 'teacher_acctid', 'schoolid', 'school_ncesid',
               'datefullyfunded', 'date_posted']

    SCALERS = [StandardScaler, MinMaxScaler]
    SCALER_NAMES = ["Standard Scaler", "MinMax Scaler"]


    def __init__(self, batch, data, file_name=DATA_FILE, ask_user=True,
                 verbose=True, test=False):
        """
        Construct a preprocessing pipeline given name of the data file.

        Inputs:
            - file_name (string): name of the data file
            - ask_user (bool): whether to ask user for configuration
            - verbose (bool): whether to make extended printing in
                preprocessing
            - drop_na (bool): whether to drop rows with missing values
            - test (bool): whether this is a pipeline built on test data

        """
        logger.info("#" + "-" * 130 + "#")
        logger.info("<BATCH %s> Creating the preprocessing pipeline for '%s'." %
                    (batch, file_name))
        self.batch = batch
        self.data = data
        self.verbose = verbose
        self.test = test
        logger.info("\tFinished reading cleaned data.\n")

        if not self.test:
            if ask_user:
                self.scaler_index = ask(self.SCALER_NAMES, "scaler")
            else:
                self.scaler_index = 0
            self.scaler = self.SCALERS[self.scaler_index]()
            logger.info(("<BATCH %s: Training data preprocessing> Pipeline "
                         "using %s.") % (self.batch,
                                         self.SCALER_NAMES[self.scaler_index]))
        else:
            dir_path = INPUT_DIR + ("Batch %s/" % self.batch)
            self.scaler = joblib.load(dir_path + 'fitted_scaler.pkl')
            logger.info("<BATCH %s: Test data preprocessing> Pre-fitted scaler "
                        "loaded.")

        self.X = None
        self.y = None

        self.extra_one_hot = []

    def con_fill_na(self):
        """
        Take the continuous variables, impute the missing features with column
        medians.

        Returns:
            (self) pipeline with missing values in the numerical columns imputed

        """
        logger.info("\n\nStart to impute missing values continuous variables:")

        for var in self.TO_FILL_CON:
            imputed = self.data[var].median()
            self.data[var] = self.data[var].fillna(imputed)

            if self.verbose:
                logger.info(("\tMissing values in '%s' imputed with column "
                             " median %4.3f.") % (var, imputed))

        return self

    def str_fill_na(self):
        """
        Fill in missing data with desired string entry.

        Returns:
            (self) pipeline with missing values in the object columns filled.

        """
        logger.info("\n\nStart to fill in missing values:")

        for var, fill in self.TO_FILL_OBJ.items():
            # if no value is provided to fill in, use the most frequent one
            if fill is None:
                fill = self.data[var].mode()[0]
            self.data[var].fillna(value=fill, inplace=True)

            if self.verbose:
                logger.info("\tFilled missing values in '%s' with '%s'." %
                            (var, fill))

    def discretize(self):
        """
        Discretizes continuous variables into multinomials.

        Returns:
            (self) pipeline with some numerical columns discretized.

        """
        logger.info("\n\nStart to discretize continuous variables:")

        for var, (qcut, bins, precision) in self.TO_DISCRETIZE.items():
            if qcut:
                self.data[var] = pd.qcut(self.data[var], bins,
                                         precision=precision).cat.codes
            else:
                self.data[var] = pd.cut(self.data[var], bins,
                                        precision=precision).cat.codes

            if self.verbose:
                if isinstance(bins, list):
                    bins = len(bins) - 1

                info = "\tDiscretized '%s' into %s %s-sized buckets."
                if self.data[var].isnull().sum() > 0:
                    info += " Here '-1' indicates that the value is missing."
                logger.info(info % (var, bins,
                                    ['differently', 'equally'][int(qcut)]))

            if bins > 2 and var not in self.extra_one_hot:
                self.extra_one_hot.append(var)

        return self

    def to_combine(self):
        """
        Combine some unnecessary levels of multinomials.

        Returns:
            (self) pipeline with less frequent levels in the multinomial columns
                combined.

        """
        logger.info("\n\nStart to combine unnecessary levels of multinomials.")

        for var, dict_combine in self.TO_COMBINE.items():
            if not dict_combine:
                dict_combine = {"YES": [val for val in self.data[var].unique()
                                        if val != "NO"]}

            for combined, lst_combine in dict_combine.items():
                if not lst_combine:
                    freqs = self.data[var].value_counts(normalize=True)
                    lst_combine = freqs[freqs < 0.05].index
                self.data.loc[self.data[var].isin(lst_combine), var] = combined

            if self.verbose:
                logger.info("\tCombinations of levels on '%s'." % var)

        return self

    def to_binary(self):
        """
        Transform variables to binaries.

        Returns:
            (self) pipeline with chosen columns transformed to binaries.

        """
        logger.info(("\n\nFinished transforming the following variables: %s to "
                     "binaries.") % (list(self.TO_BINARIES.keys())))

        for var, cats in self.TO_BINARIES.items():
            enc = OrdinalEncoder(categories=cats)
            self.data[var] = enc.fit_transform(np.array(self.data[var]).\
                                               reshape(-1, 1))

        return self

    def extract_date(self):
        """
        Extract date information (year, month of year, day of week) from
        datetime columns.

        """
        logger.info("\n\nStart to extract time from datetime variables.")

        for var, datetime_extract in self.TO_EXTRACT_DATE_TIME.items():
            to_extract = {"year": self.data[var].dt.year,
                          "month": self.data[var].dt.month,
                          "weekday": self.data[var].dt.weekday,
                          "day": self.data[var].dt.day}

            for extract in datetime_extract:
                new_col = var + "_" + extract
                self.data[new_col] = to_extract[extract]
                if new_col not in self.extra_one_hot:
                    self.extra_one_hot.append(new_col)
                if self.verbose:
                    logger.info("\tExtracted %s from '%s' into '%s'." %
                                (extract, var, new_col))

    def one_hot(self):
        """
        Creates binary/dummy variables from multinomials, drops the original
        and inserts the dummies back.

        Returns:
            (self) pipeline with one-hot-encoding applied on categorical vars.

        """
        logger.info(("\n\nFinished applying one-hot-encoding to the following "
                     "categorical variables: %s\n\n") % self.TO_ONE_HOT)

        for var in self.TO_ONE_HOT + self.extra_one_hot:
            dummies = pd.get_dummies(self.data[var], prefix=var)
            self.data.drop(var, axis=1, inplace=True)
            self.data = pd.concat([self.data, dummies], axis=1)

        return self

    def feature_target_split(self):
        """
        Drop rows with missing labels, drop some columns that are not relevant
        or have too many missing values, split the features (X) and target (y)
        Write columns names to "feature_names.txt" in the output directory.

        """
        self.data.dropna(axis=0, subset=[self.TARGET], inplace=True)
        self.y = self.data[self.TARGET]
        self.data.drop(self.TARGET, axis=1, inplace=True)
        logger.info("Finished extracting the target (y).")

        self.data.drop(self.TO_DROP, axis=1, inplace=True)
        self.data.dropna(axis=0, inplace=True)
        self.X = self.data
        logger.info("Finished extracting the features (X).")

        file_name = [TRAIN_FEATURES_FILE, TEST_FEATURES_FILE][int(self.test)]
        dir_path = OUTPUT_DIR + ("Batch %s/" % self.batch)
        create_dirs(dir_path)

        with open(dir_path + file_name, 'w') as file:
            file.write(",".join(self.X.columns))
            logger.info("\t%s feature names wrote to '%s' under directory '%s'"
                        % (["Train", "Test"][int(self.test)], file_name,
                           dir_path))

    def compare_train_test(self):
        """
        Compare the features in the training and test set after preprocessing.
        For those in the training set but not the test set, insert a column with
        all zeros at the same column index in the test set. For those in the
        test set but are not in the training set, drop them from the test set.

        """
        train_features = read_feature_names(OUTPUT_DIR + ("Batch %s/" % self.batch),
                                            'train_features.txt')
        test_features = read_feature_names(OUTPUT_DIR + ("Batch %s/" % self.batch),
                                           'test_features.txt')

        to_drop = [var for var in test_features if var not in train_features]
        self.data.drop(to_drop, axis=1, inplace=True)
        logger.info(("\n\n%s are in the test set but are not in the training "
                     "set, dropped from the test set.") % to_drop)

        to_add = [(i, var) for (i, var) in enumerate(train_features)
                  if var not in test_features]
        logger.info(("Start to add those are in the training set but not the "
                     "test set to the test set:"))
        for i, var in to_add:
            self.data.insert(loc=i, column=var, value=0)
            if self.verbose:
                logger.info("\t'%s' added to the %sth column of the test set "
                            "with all zeros." % (var, i))

    def scale(self):
        """
        Fit and transform the scaler on the training data and return the
        scaler data to scale test data.

        Returns:
            (self) pipeline with scaled data. The fitted scaler dumped to
                "../data/"

        """
        logger.info("\n")

        if not self.test:
            self.scaler.fit(self.X.values.astype(float))
            dir_path = INPUT_DIR + ("Batch %s/" % self.batch)
            create_dirs(dir_path)
            joblib.dump(self.scaler, dir_path + 'fitted_scaler.pkl')
            logger.info(("<Training data preprocessing> Fitted scaler dumped "
                         "to '%s' under directory '%s'.") % ('fitted_scaler.pkl',
                                                             dir_path))

        self.X = self.scaler.transform(self.X.values.astype(float))
        logger.info("Finished scaling the feature matrix.")

        return self

    def save_data(self):
        """
        Saves the feature matrix and target as numpy arrays in the output
        directory.

        """
        if self.test:
            extension = "_test.npy"
            logger.info("<TEST SET SHAPE> n: %s, m: %s" % self.X.shape)
        else:
            extension = "_train.npy"
            logger.info("<TRAINING SET SHAPE> n: %s, m: %s\n" % self.X.shape)
        dir_path = OUTPUT_DIR + ("Batch %s/" % self.batch)
        create_dirs(dir_path)

        np.save(dir_path + "X" + extension, self.X, allow_pickle=False)
        np.save(dir_path + "y" + extension, self.y.values.astype(float),
                allow_pickle=False)

        logger.info(("\n\nSaved the resulting NumPy matrices to directory '%s'. "
                     "Features are in 'X%s' and target is in 'y%s'.") %
                     (dir_path, extension, extension))

    def preprocess(self):
        """
        Finish preprocessing the data file.

        """
        self.con_fill_na().str_fill_na()
        self.discretize().to_combine().to_binary().extract_date()
        self.one_hot().feature_target_split()
        if self.test:
            self.compare_train_test()
        self.scale().save_data()

        logger.info("\n\n<BATCH %s: Finished processing %s data>" %
                    (self.batch, ["training", "test"][int(self.test)]))
        logger.info("#" + "-" * 130 + "#\n\n")


#----------------------------------------------------------------------------#
if __name__ == "__main__":

    desc = ("Build a preprocessing pipeline that helps user preprocess "
            "training and test data from the temporal train test split on the "
            "donation project data. Fill in missing values, discretize "
            "continuous variables, generate new features, deal with categorical "
            "variables with multiple levels, scale data, and save preprocessed "
            "data.")
    parser = argparse.ArgumentParser(description=desc)

    parser.add_argument('--ask', dest='ask_user', type=int, default=0,
                        help=(
                            "Please specify whether the script should ask for "
                            "user configuration to run on one model-metrics "
                            "pair or all of them (1 for true or 0 for false)."))
    parser.add_argument('--verbose', dest='verbose', type=int, default=1,
                        help=("Please specify whether the pipeline should be "
                              "verbose (1 for true or 0 for false)."))
    args = parser.parse_args()
    args_dict = {'ask_user': bool(args.ask_user),
                 'verbose': bool(args.verbose)}

    logger.info("**" + "-" * 180 + "**")
    data = read_data(DATA_FILE)
    pairs = temporal_split(data, 'date_posted', "4M", "60D")

    for i, (train, test) in enumerate(pairs):
        training_pipeline = FeaturePipeLine(i, train, **args_dict, test=False)
        training_pipeline.preprocess()

        test_pipeline = FeaturePipeLine(i, test, **args_dict, test=True)
        test_pipeline.preprocess()

    logger.info("**" + "-" * 180 + "**")