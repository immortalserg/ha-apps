import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "libretranslate" / "start.py"
spec = importlib.util.spec_from_file_location("ha_libretranslate", MODULE)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class TestLibreTranslateConfig(unittest.TestCase):
    def test_defaults(self):
        env = app.configure({})
        self.assertEqual(env["LT_HOST"], "0.0.0.0")
        self.assertEqual(env["LT_PORT"], "5000")
        self.assertEqual(env["LT_LOAD_ONLY"], "en,fr,de,ru")
        self.assertEqual(env["LT_UPDATE_MODELS"], "false")

    def test_custom_options(self):
        env = app.configure({"languages": "en,fr", "threads": 3,
                             "char_limit": 3000, "req_limit": 5,
                             "update_models": True})
        self.assertEqual(env["LT_THREADS"], "3")
        self.assertEqual(env["LT_UPDATE_MODELS"], "true")

    def test_invalid_languages(self):
        with self.assertRaises(ValueError):
            app.configure({"languages": "en;rm -rf /"})

    def test_invalid_limit(self):
        with self.assertRaises(ValueError):
            app.configure({"char_limit": -1})


if __name__ == "__main__":
    unittest.main()
