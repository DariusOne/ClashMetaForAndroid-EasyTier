/* Disposable CI packet probe. Runs as Android shell UID, NOT the excluded VPN
 * application UID. No credentials, external hosts or arbitrary commands. */
#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static void fail(const char *code) { fprintf(stderr, "%s\n", code); exit(1); }
static int wait_read(int fd) {
    struct pollfd p = {.fd=fd, .events=POLLIN};
    return poll(&p, 1, 15000) == 1;
}
static int open_socket(int udp) {
    int fd = socket(AF_INET, udp ? SOCK_DGRAM : SOCK_STREAM, 0);
    if (fd < 0) fail("SOCKET_FAILED");
    struct timeval timeout = {.tv_sec=8};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    return fd;
}
static void send_all(int fd, const char *data, size_t length) {
    while (length) {
        ssize_t n = send(fd, data, length, MSG_NOSIGNAL);
        if (n <= 0) fail("SEND_FAILED");
        data += n; length -= n;
    }
}
int main(int argc, char **argv) {
    if (argc != 4) fail("ARGUMENTS_INVALID");
    int udp = !strcmp(argv[1], "udp-client") || !strcmp(argv[1], "udp-server");
    int server = !strcmp(argv[1], "tcp-server") || !strcmp(argv[1], "udp-server");
    if (!udp && !server && strcmp(argv[1], "tcp-client")) fail("MODE_INVALID");
    char *end = NULL;
    long port = strtol(argv[3], &end, 10);
    if (*end || port < 1024 || port > 65535) fail("PORT_INVALID");
    struct sockaddr_in target = {.sin_family=AF_INET, .sin_port=htons(port)};
    if (inet_pton(AF_INET, argv[2], &target.sin_addr) != 1) fail("IP_INVALID");
    if (server) {
        int fd = open_socket(udp);
        if (bind(fd, (void *)&target, sizeof(target))) fail("BIND_FAILED");
        if (!udp && listen(fd, 8)) fail("LISTEN_FAILED");
        puts("READY"); fflush(stdout);
        for (int i=0; i<5; i++) {
            if (!wait_read(fd)) fail("READ_TIMEOUT");
            char buffer[128];
            struct sockaddr_in peer;
            socklen_t length = sizeof(peer);
            if (udp) {
                ssize_t n = recvfrom(fd, buffer, sizeof(buffer), 0, (void *)&peer, &length);
                if (n <= 0 || sendto(fd, buffer, n, 0, (void *)&peer, length) != n) fail("UDP_ECHO_FAILED");
            } else {
                int child = accept(fd, NULL, NULL);
                if (child < 0 || !wait_read(child)) fail("ACCEPT_FAILED");
                size_t total = 0;
                do {
                    if (total == sizeof(buffer) || !wait_read(child)) fail("TCP_READ_FAILED");
                    ssize_t n = recv(child, buffer + total, sizeof(buffer) - total, 0);
                    if (n <= 0) fail("TCP_READ_FAILED");
                    total += n;
                } while (buffer[total - 1] != '\n');
                send_all(child, buffer, total); close(child);
            }
        }
        close(fd);
    } else {
        for (int i=0; i<5; i++) {
            int fd = open_socket(udp);
            if (connect(fd, (void *)&target, sizeof(target))) fail("CONNECT_FAILED");
            char request[64], response[128];
            int length = snprintf(request, sizeof(request), "cmfa-native-packet-%d\n", i);
            send_all(fd, request, length);
            if (!wait_read(fd)) fail("READ_TIMEOUT");
            int total = 0;
            while (total < length) {
                ssize_t n = recv(fd, response + total, sizeof(response) - total, 0);
                if (n <= 0) fail("RECV_FAILED");
                total += n;
                if (udp) break;
            }
            if (total != length || memcmp(request, response, length)) fail("PAYLOAD_MISMATCH");
            close(fd);
        }
    }
    puts("PASS 5/5");
    return 0;
}
