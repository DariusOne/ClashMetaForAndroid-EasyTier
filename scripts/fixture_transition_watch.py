"""Bounded helper for the synthetic mesh transition probe; no secret inputs."""
import json
import queue
import subprocess
import threading


class TransitionWatch:
    def __init__(self, command):
        self.events = queue.Queue()
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        encoding='utf-8', errors='replace')
        self.lines = []
        def consume():
            for line in self.process.stdout:
                self.lines.append(line.strip())
                self.events.put(line.strip())
        self.reader = threading.Thread(target=consume, daemon=True)
        self.reader.start()

    def ready(self):
        if self.events.get(timeout=12) != 'WATCH_READY':
            raise RuntimeError('Transition probe did not establish a baseline')

    def finish(self, sources):
        self.process.wait(timeout=12)
        self.reader.join(timeout=2)
        if self.reader.is_alive():
            raise RuntimeError('Transition probe output did not close')
        values = [json.loads(line) for line in self.lines if line.startswith('{')]
        if len(values) != 1:
            raise RuntimeError('Transition probe result missing')
        result = values[0]
        sources = sources()
        result.update({'returncode':self.process.returncode, 'peer_observed':len(sources),
                       'peer_wrong_source':sum(ip != '10.126.0.2' for ip in sources)})
        result['passed'] = (self.process.returncode == 0 and result['received'] > 0
                            and result['wrong_source'] == 0 and result['invalid_payload'] == 0
                            and result['peer_wrong_source'] == 0)
        return result

    def close(self):
        if self.process.poll() is None:
            try:
                # Let the remote eight-second probe exit while the VPN is
                # still present. Killing only host adb could orphan it.
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=2)
