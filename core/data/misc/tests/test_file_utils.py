'''
test_file_utils.py

Copyright 2006 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import unittest
import os

from core.data.misc.file_utils import days_since_file_update


class TestFileUtils(unittest.TestCase):

    def test_days_since_file_update_true(self):
        filename = os.path.join('core', 'data', 'misc', 'file_utils.py')
        result = days_since_file_update(filename, 0)
        self.assertTrue(result)

    def test_days_since_file_update_not_exists(self):
        filename = os.path.join('core', 'data', 'misc', 'notexists.py')
        self.assertRaises(ValueError, days_since_file_update, filename, 0)
        
    def test_days_since_file_update_false(self):
        filename = os.path.join('core', 'data', 'misc', 'file_utils.py')
        result = days_since_file_update(filename, 309 ** 32)
        self.assertFalse(result)
