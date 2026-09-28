"""Exercise transient and persistent Windows metadata replacement failures."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from run_experiment_queue import save


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = root / 'planning/test_tmp'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        target = Path(directory) / 'state.json'
        original = Path.replace
        calls = []

        def transient(path, destination):
            calls.append(1)
            if len(calls) < 4:
                raise PermissionError('simulated sharing conflict')
            return original(path, destination)

        with patch.object(Path, 'replace', transient), patch('run_experiment_queue.time.sleep') as delay:
            save(target, {'status': 'test'})
            assert len(calls) == 4 and delay.call_count == 3
        assert json.loads(target.read_text()) == {'status': 'test'}
        with patch.object(Path, 'replace', side_effect=PermissionError('persistent')) as replace:
            with patch('run_experiment_queue.time.sleep'):
                try:
                    save(target, {'status': 'must_not_replace'})
                except PermissionError:
                    pass
                else:
                    raise AssertionError('Persistent error was hidden')
                assert replace.call_count == 40
        assert json.loads(target.read_text()) == {'status': 'test'}
    print('QUEUE_STATE_TEST_PASS: transient recovery, bounded retries, previous state preserved')


if __name__ == '__main__':
    main()
