#!/usr/bin/env python3
"""The filter's pairing screen — an MM leak found during ticket #7's real run.
Run from pipeline/:  python3 -m unittest test_filter -v
"""
import unittest
from filter import queer_screen, cowboy_screen


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


class LgbtqSpellingTests(unittest.TestCase):
    """The 2026-09-22 live leak: a pick shipped with the genre string
    "LGBTQIA+ Romance Books Romance" because no marker covered the spellings."""

    def test_the_live_genre_string_is_screened(self):
        self.assertTrue(queer_screen('Hockey Season Homewreckers', 'LGBTQIA+ Romance Books Romance'))

    def test_spellings(self):
        self.assertTrue(queer_screen('title', 'Lesbian Romance'))
        self.assertTrue(queer_screen('title', 'Sapphic Fiction'))
        self.assertTrue(queer_screen('title', 'LGBT Romance'))
        self.assertTrue(queer_screen('title', 'gay fiction'))
        self.assertTrue(queer_screen('A Gay Affair', 'romance'))           # standalone 'gay'
        self.assertTrue(queer_screen('title', 'Boys Love'))
        self.assertTrue(queer_screen('title', 'Transgender Romance'))
        self.assertTrue(queer_screen('title', 'non-binary love story'))

    def test_ff_and_menage_markers(self):
        self.assertTrue(queer_screen('title', 'F/F romance'))
        self.assertTrue(queer_screen('FF Romance: A Novel', 'romance'))
        self.assertTrue(queer_screen('title', 'MMF menage'))

    def test_innocent_words_still_pass(self):
        self.assertFalse(queer_screen('Office Romance', 'contemporary romance'))  # 'ff' inside a word
        self.assertFalse(queer_screen('The Gaylord Inheritance', 'historical romance'))  # 'gay' inside a word
        self.assertFalse(queer_screen('Coffee and Storms', 'romance'))


class CowboyScreenTests(unittest.TestCase):
    """Her rule (2026-09-22): no cowboy/cowgirl/western characters, any variant."""

    def test_title_hits(self):
        self.assertTrue(cowboy_screen('Cowboy Up', 'romance'))
        self.assertTrue(cowboy_screen('Come Home to the Cowboys', 'Contemporary Romance Books Romance'))
        self.assertTrue(cowboy_screen('Heart of the Ranch', 'romance'))
        self.assertTrue(cowboy_screen('Cowgirl Summer', 'romance'))

    def test_genre_hits(self):
        # real records from the September candidate file
        self.assertTrue(cowboy_screen('Reckless Skye', 'Western Romance Books Romance'))
        self.assertTrue(cowboy_screen('The Great Alone', 'Western Romance Books Romance'))
        self.assertTrue(cowboy_screen('title', 'Rodeo Romance'))

    def test_innocent_titles_pass(self):
        self.assertFalse(cowboy_screen('Stormy Weather', 'contemporary romance'))
        self.assertFalse(cowboy_screen('West of Forever', 'romance'))     # 'west' != 'western'
        self.assertFalse(cowboy_screen('Second Serve', 'Sports Romance'))


if __name__ == '__main__':
    unittest.main()
