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

class PubClassTests(unittest.TestCase):
    """#47: the imprints the Goodreads reference surfaced must classify as trad
    (they are big-5 houses), and nothing may masquerade as indie."""

    def test_big_five_imprints_are_trad(self):
        from filter import pub_class
        for p in ('Crown', 'William Morrow', 'Penguin Publishing Group',
                  'Knopf Doubleday Publishing', 'Park Row Books', 'HarperCollins',
                  'Macmillan Publishers', 'Dutton', 'St. Martin\'s Publishing Group'):
            self.assertEqual(pub_class(p), 'trad', p)

    def test_indie_and_unknown_stay_distinct(self):
        from filter import pub_class
        self.assertEqual(pub_class('Independently published'), 'indie')
        self.assertEqual(pub_class('Montlake'), 'indie')
        self.assertEqual(pub_class(''), 'unknown')
        self.assertEqual(pub_class('Some Tiny Press'), 'unknown')


class DarkRomanceRuleTests(unittest.TestCase):
    """Her rule reversed (2026-09-23): dark romance is WANTED — especially dark
    academia. A dark-academia candidate passes screening with a positive hint,
    and all four rule surfaces say so (no stale 'no dark romance' anywhere)."""

    def test_dark_academia_candidate_is_hinted_not_screened(self):
        from filter import dark_hint
        self.assertTrue(dark_hint('Eternal is the Night', 'Dark Academia Romance'))
        self.assertTrue(dark_hint('title', 'Gothic Romance'))
        self.assertTrue(dark_hint('A Study in Shadows', 'Dark Academia'))
        self.assertTrue(dark_hint('title', 'morally grey anti-hero romance'))
        self.assertTrue(dark_hint('The Quiet Ledger', 'Contemporary Romance', 'a dark academia series'))
        self.assertFalse(dark_hint('The Cruel Prince', 'Romantasy'))
        self.assertFalse(dark_hint('The Summer Pact', 'Contemporary Romance'))
        self.assertFalse(dark_hint('Hockey Captain', 'Sports Romance'))

    def test_all_four_rule_surfaces_agree(self):
        import curate, build, os
        self.assertIn('Dark romance is welcome', curate.HARD_RULES)
        self.assertNotIn('No dark romance', curate.HARD_RULES)
        self.assertIn('dark romance & dark academia welcome', build.CRITERIA)
        self.assertNotIn('no dark romance', build.CRITERIA)
        tp = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'taste-prompt.md')).read()
        self.assertIn('Dark romance is welcome', tp)
        self.assertNotIn('NO dark romance', tp)

    def test_rules_block_states_it_honestly(self):
        import os
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'filter.py')).read()
        self.assertIn("'dark_romance_welcome': True", src)
        self.assertNotIn("'no_dark': True", src)
