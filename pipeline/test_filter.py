#!/usr/bin/env python3
"""The filter's pairing screen — an MM leak found during ticket #7's real run.
Run from pipeline/:  python3 -m unittest test_filter -v
"""
import unittest
from filter import queer_screen


class PairingScreenTests(unittest.TestCase):
    def test_phrase_hits(self):
        self.assertTrue(queer_screen('title', 'gay romance'))
        self.assertTrue(queer_screen('An MM Romance Novel', 'romance'))
        self.assertTrue(queer_screen('title', 'wlw romance'))

    def test_standalone_markers(self):
        # the leak: these slipped through the substring list on 2026-09-21
        self.assertTrue(queer_screen('Hockey Hearts: An MM Hockey Romance', 'Romance Books Contemporary Romance'))
        self.assertTrue(queer_screen('Icebound: A Dark MM Romance', 'Romance for Young Adults Books'))
        self.assertTrue(queer_screen('A Match M/M Style', 'romance'))
        self.assertTrue(queer_screen('title', 'm x m pairing'))

    def test_mf_titles_pass(self):
        self.assertFalse(queer_screen('The MMXX Summer', 'romance'))       # not a standalone mm
        self.assertFalse(queer_screen('Hockey Captain', 'Sports Romance'))
        self.assertFalse(queer_screen('Summer Storm', 'romance'))          # 'mm' inside a word
        self.assertFalse(queer_screen('A Romantic Comedy', 'rom-com'))


if __name__ == '__main__':
    unittest.main()
