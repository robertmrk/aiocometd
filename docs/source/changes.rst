Changelog
=========


0.4.4 (2019-02-26)
------------------

- Refactor the websocket transport implementation to use a single connection
  per client

0.4.3 (2019-02-12)
------------------

- Fix reconnection issue on Salesforce Streaming API

0.4.2 (2019-01-15)
------------------

- Fix the handling of invalid websocket transport responses
- Fix the handling of failed subscription responses

0.4.1 (2019-01-04)
------------------

- Add documentation links

0.4.0 (2019-01-04)
------------------

- Add type hints
- Add integration tests

0.3.1 (2018-06-15)
------------------

- Fix premature request timeout issue

0.3.0 (2018-05-04)
------------------

- Enable the usage of third party JSON libraries
- Fix detection and recovery from network failures

0.2.3 (2018-04-24)
------------------

- Fix RST rendering issues

0.2.2 (2018-04-24)
------------------

- Fix documentation typos
- Improve examples
- Reorganise documentation

0.2.1 (2018-04-21)
------------------

- Add PyPI badge to README

0.2.0 (2018-04-21)
------------------

- Supported transports:
   - ``long-polling``
   - ``websocket``
- Automatic reconnection after network failures
- Extensions
