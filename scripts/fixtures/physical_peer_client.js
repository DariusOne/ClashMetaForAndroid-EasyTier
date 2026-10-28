'use strict';
const net = require('node:net');
const dgram = require('node:dgram');
const mode = process.argv[2];
const port = Number(process.argv[3]);
if (!['tcp', 'udp'].includes(mode) || !Number.isInteger(port) || port < 1024 || port > 65535) process.exit(2);
async function once(i) {
  const payload = Buffer.from(`physical-native-peer-${i}\n`);
  return new Promise((resolve, reject) => {
    const socket = mode === 'udp' ? dgram.createSocket('udp4') : new net.Socket();
    let received = Buffer.alloc(0);
    const timer = setTimeout(() => done(new Error('timeout')), 8000);
    let finished = false;
    function done(error) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (mode === 'udp') socket.close(); else socket.destroy();
      if (error) reject(error); else resolve();
    }
    socket.on('error', done);
    function data(buffer) {
      received = Buffer.concat([received, buffer]);
      if (received.length >= payload.length) done(received.equals(payload) ? undefined : new Error('payload'));
    }
    if (mode === 'udp') {
      socket.on('message', data);
      socket.send(payload, port, '10.126.0.2');
    } else {
      socket.on('data', data);
      socket.connect(port, '10.126.0.2', () => socket.write(payload));
    }
  });
}
(async () => {
  for (let i=0; i<5; i++) await once(i);
  console.log('PASS 5/5');
})().catch(() => { console.error('PEER_PROBE_FAILED'); process.exitCode = 1; });
