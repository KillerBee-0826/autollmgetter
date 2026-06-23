import logging
import unittest

from cloudwatch_logger import get_logger, setup_cloudwatch_logger, setup_minimal_logger


class CloudWatchLoggerTests(unittest.TestCase):
    def test_setup_cloudwatch_logger_returns_configured_logger(self):
        logger = setup_cloudwatch_logger("test-cloudwatch", logging.DEBUG)

        self.assertEqual(logger.name, "test-cloudwatch")
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(len(logger.handlers), 1)
        self.assertFalse(logger.propagate)

    def test_setup_cloudwatch_logger_does_not_duplicate_handlers(self):
        logger = setup_cloudwatch_logger("test-cloudwatch-duplicate")
        first_handler = logger.handlers[0]

        logger = setup_cloudwatch_logger("test-cloudwatch-duplicate")

        self.assertEqual(len(logger.handlers), 1)
        self.assertIsNot(logger.handlers[0], first_handler)

    def test_setup_minimal_logger_returns_logger_without_clearing_handlers(self):
        logger = setup_cloudwatch_logger("test-minimal")
        handler_count = len(logger.handlers)

        minimal = setup_minimal_logger("test-minimal", logging.WARNING)

        self.assertIs(minimal, logger)
        self.assertEqual(minimal.level, logging.WARNING)
        self.assertEqual(len(minimal.handlers), handler_count)

    def test_get_logger_returns_same_logger_instance(self):
        logger = setup_cloudwatch_logger("test-get-logger")

        self.assertIs(get_logger("test-get-logger"), logger)


if __name__ == "__main__":
    unittest.main()
