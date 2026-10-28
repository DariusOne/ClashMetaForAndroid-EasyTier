// Disposable Linux-container echo peer. Only synthetic packet fixtures; no
// production network inputs. Counters include empty accepted TCP connections.
'use strict';
const fs = require('node:fs');
const net = require('node:net');
const dgram = require('node:dgram');
const stats = {tcp: [], udp: [], reject: []};
const save = () => {
  fs.writeFileSync('/tmp/packet-counts.tmp', JSON.stringify(stats));
  fs.renameSync('/tmp/packet-counts.tmp', '/tmp/packet-counts.json');
};
for (const [name, port] of [['tcp', 30101], ['reject', 30103]]) {
  net.createServer(socket => {
    stats[name].push(socket.remoteAddress);
    save();
    socket.setTimeout(10000, () => socket.destroy());
    socket.on('error', () => {});
    socket.on('data', data => socket.write(data));
  }).listen(port, '0.0.0.0');
}
const udp = dgram.createSocket('udp4');
udp.on('message', (data, remote) => {
  stats.udp.push(remote.address);
  save();
  udp.send(data, remote.port, remote.address);
});
udp.bind(30102, '0.0.0.0');
save();
