"""pick_book must survive model-written field drift (ticket #31).

A live incident: the model returned spice as the string "3.5", a bare int()
raised ValueError inside build.py, and the shelf rendered empty. These tests
pin the tolerant coercion so a drifted value can never blank the page again.
"""
import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import pick_book, _int


def _book(**kw):
    b = {'title': 'Test Book', 'author': 'Test Author'}
    b.update(kw)
    return b


class TestPickCoercion(unittest.TestCase):
    def test_string_spice_is_coerced(self):
        self.assertEqual(pick_book(_book(spice='3.5'), None, None)['spice'], 3)

    def test_numeric_string_spice_is_coerced(self):
        self.assertEqual(pick_book(_book(spice='4'), None, None)['spice'], 4)

    def test_float_spice_is_coerced(self):
        self.assertEqual(pick_book(_book(spice=2.9), None, None)['spice'], 2)

    def test_junk_spice_falls_back_to_default(self):
        self.assertEqual(pick_book(_book(spice='spicy'), None, None)['spice'], 3)

    def test_bare_string_mmc_is_coerced(self):
        self.assertEqual(pick_book(_book(mmc='4'), None, None)['mmc'], 4)

    def test_dict_mmc_string_score_is_coerced(self):
        self.assertEqual(pick_book(_book(mmc={'score': '5'}), None, None)['mmc'], 5)

    def test_missing_fields_keep_defaults(self):
        got = pick_book(_book(), None, None)
        self.assertEqual((got['spice'], got['mmc']), (3, 3))

    def test_int_helper_never_raises(self):
        for v in (None, '', 'x', [], {}, object()):
            self.assertEqual(_int(v, 7), 7)


if __name__ == '__main__':
    unittest.main()
