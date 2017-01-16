# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import hashlib
import os
import random

__author__ = "Tyson Smith"
__credits__ = ["Tyson Smith"]

class Template(object):
    def __init__(self, file_name):
        self._data = None # file data
        self._data_hash = None # SHA1 hash of data
        self.extension = None # file extension
        self.file_name = file_name # file name of the template

        if self.file_name is None:
            raise IOError("File does not exist: %s" % self.file_name)

        if "." in self.file_name:
            self.extension = os.path.splitext(self.file_name)[1].lstrip(".")


    def _load_and_hash_data(self):
        # read data from disk
        if not os.path.isfile(self.file_name):
            raise IOError("File does not exist: %s" % self.file_name)
        with open(self.file_name, "rb") as in_fp:
            self._data = in_fp.read()

        # calculate SHA1 hash
        self._data_hash = hashlib.sha1(self._data).hexdigest()


    def get_data(self):
        """
        get_data()
        Provide the raw template data to the caller. If data has not been loaded
        _load_and_hash_data() is called

        returns template data from file.read()
        """

        # load template data the first time it is requested
        if self._data is None:
            self._load_and_hash_data()

        return self._data


    def get_hash(self):
        """
        get_hash()
        Provide the template data hash to the caller. If the SHA1 hash has not been calculated yet
        _load_and_hash_data() is called.

        returns SHA1 hash string
        """

        if self._data_hash is None:
            self._load_and_hash_data()

        return self._data_hash


class TestCase(object):
    def __init__(self, landing_page, corpman_name, template=None):
        self.corpman_name = corpman_name
        self.landing_page = landing_page
        self.template = template
        self._test_files = [] # contains TestFile(s) that make up a test case
        self._optional_files = [] # contains TestFile(s) that are not strictly required


    def add_testfile(self, test_file):
        if not isinstance(test_file, TestFile):
            raise TypeError("add_testfile() only accepts TestFile objects")

        self._test_files.append(test_file)
        if not test_file.required:
            self._optional_files.append(test_file.file_name)


    def dump(self, log_dir, info_file=False):
        """
        dump(log_dir)
        Write all the test case data to the filesystem.
        This includes:
        - the generated test case
        - template file details
        All data will be located in log_dir.

        returns None
        """

        # save test file page
        for test_file in self._test_files:
            with open(os.path.join(log_dir, test_file.file_name), "wb") as out_fp:
                out_fp.write(test_file.data)

        # save test case and template file information
        if info_file:
            with open(os.path.join(log_dir, "test_info.txt"), "w") as out_fp:
                out_fp.write("[Grizzly template/test case details]\n")
                out_fp.write("Corpus Manager: %s\n" % self.corpman_name)
                out_fp.write("Landing Page:   %s\n" % self.landing_page)
                if self.template is not None:
                    out_fp.write("Template File:  %s\n" % os.path.basename(self.template.file_name))
                    out_fp.write("Template SHA1:  %s\n" % self.template.get_hash())


    def get_optional(self):
        if self._optional_files:
            return self._optional_files
        return None


class TestFile(object):
    def __init__(self, file_name, data, required=True):
        self.file_name = file_name # name including path relative to wwwroot
        self.data = data
        self.required = required # this file must be served to complete test case


class CorpusManager(object):
    """
    CorpusManager is the base class that is used when creating specific corpus
    managers.
    """

    key = None # this must be overloaded in the subclass

    def __init__(self, path, accepted_extensions=None, aggression=0.001, is_replay=False, rotate=10):
        self._active_template = None
        self._corpus_path = path # directory to look for template files in
        self._fuzzer = None
        self._generated = 0 # number of test cases generated
        self._is_replay = is_replay
        self._rotate_period = 0 if is_replay else rotate # how often a new template is selected
        self._templates = list() # fuzzed test cases will be based on these files
        self._use_transition = True # use transition page between test cases

        self._init_fuzzer(aggression)
        self._scan_for_templates(accepted_extensions)


    def _init_fuzzer(self, aggression):
        """
        _init_fuzzer is meant to be implemented in subclass
        """


    def _scan_for_templates(self, accepted_extensions=None):
        # ignored_list is a list of ignored files (usually auto generated OS files)
        ignored_list = ["desktop.ini", "thumbs.db"]
        self._templates = list()

        if os.path.isdir(self._corpus_path):
            for d_name, _, filenames in os.walk(self._corpus_path):
                for f_name in filenames:
                    # check for unwanted files
                    if f_name.startswith(".") or f_name.lower() in ignored_list:
                        continue
                    if accepted_extensions:
                        ext = os.path.splitext(f_name)[1].lstrip(".").lower()
                        if ext not in accepted_extensions:
                            continue
                    test_file = os.path.abspath(os.path.join(d_name, f_name))
                    # skip empty files
                    if os.path.getsize(test_file) > 0:
                        self._templates.append(test_file)
        elif os.path.isfile(self._corpus_path) and os.path.getsize(self._corpus_path) > 0:
            self._templates.append(os.path.abspath(self._corpus_path))

        # TODO: should be force CMs to have templates???
        if not self._templates:
            raise IOError("Could not find test case(s) at %s" % self._corpus_path)

        # order list for replay to help manually remove items if needed
        if self._is_replay:
            # reverse since we use .pop()
            self._templates.sort(reverse=True)


    @staticmethod
    def to_data_url(data, mime_type=None):
        if mime_type is None:
            mime_type = "application/octet-stream"
        return "data:%s;base64,%s" % (mime_type, base64.standard_b64encode(data))


    def _generate(self, test, redirect_page, mime_type=None):
        raise NotImplementedError("_generate must be implemented in the subclass")


    def generate(self, mime_type=None):
        # check if we should choose a new active template
        if self._rotate_period > 0 and (self._generated % self._rotate_period) == 0:
            # rescan test case directory to pick up any new additions
            self._scan_for_templates()
            # only switch templates if we have more than one
            if len(self._templates) > 1:
                self._active_template = None

        # choose a template
        if self._is_replay:
            self._active_template = Template(self._templates.pop())
        elif self._active_template is None:
            self._active_template = Template(random.choice(self._templates))

        # create test case object and landing page names
        test = TestCase(
            "test_page_%04d.html" % self._generated,
            corpman_name=self.key,
            template=self._active_template)
        if self._use_transition:
            redirect_page = "transition_%04d.html" % self._generated
            rd_file = TestFile(
                redirect_page,
                "<script>window.location='test_page_%04d.html';</script>" % (self._generated + 1))
            test.add_testfile(rd_file) # add redirect file to test case
        else:
            redirect_page = "test_page_%04d.html" % (self._generated + 1)

        self._generate(test, redirect_page, mime_type=mime_type)
        self._generated += 1

        return test


    def get_active_file_name(self):
        try:
            return self._active_template.file_name
        except AttributeError:
            return None


    def landing_page(self):
        return "test_page_%04d.html" % (self._generated)


    def size(self):
        return len(self._templates)


    # TODO: rename update_test() -> finish_test()
    # TODO: update_test() and generate() should not take test as a param
    # it should be a class member.
    def update_test(self, clone_log_cb, test):
        """
        update_test is meant to be implemented in subclass
        """
        return None
