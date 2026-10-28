/* Android NDK/Bionic counterpart to the raw Linux Go handover probe.
 * Fixed synthetic destination; same shell UID, duration and success contract. */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifdef TRANSITION_PROBE_UNIT_TEST
#define TARGET "127.0.0.1"
#define DURATION 250
#else
#define TARGET "10.126.0.1"
#define DURATION 8000
#endif

static int64_t now_ms(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) exit(2);
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int wait_fd(int fd, short events, int64_t deadline) {
    struct pollfd p = {.fd=fd, .events=events};
    for (;;) {
        int64_t left = deadline - now_ms();
        if (left <= 0) return 0;
        int result = poll(&p, 1, (int)left);
        if (result > 0) return 1;
        if (result == 0 || errno != EINTR) return 0;
    }
}

static int connected(int fd, const struct sockaddr_in *target, int64_t deadline) {
    if (connect(fd, (const void *)target, sizeof(*target)) == 0) return 1;
    if (errno != EINPROGRESS || !wait_fd(fd, POLLOUT, deadline)) return 0;
    int error = 0;
    socklen_t size = sizeof(error);
    return getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) == 0 && error == 0;
}

static int transfer(int fd, int udp, const char *request, size_t length, int64_t deadline) {
    size_t sent = 0, received = 0;
    char response[128];
    while (sent < length) {
        if (now_ms() >= deadline) return 0;
        ssize_t n = send(fd, request + sent, length - sent, MSG_NOSIGNAL);
        if (n > 0) { sent += (size_t)n; continue; }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && wait_fd(fd, POLLOUT, deadline)) continue;
        return 0;
    }
    while (received < length) {
        if (now_ms() >= deadline) return 0;
        ssize_t n = recv(fd, response + received, sizeof(response) - received, 0);
        if (n > 0) {
            received += (size_t)n;
            if (udp || received >= length) break;
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && wait_fd(fd, POLLIN, deadline)) continue;
        return 0;
    }
    return received == length && !memcmp(request, response, length) ? 1 : -1;
}

int main(int argc, char **argv) {
    if (argc != 3 || (strcmp(argv[1], "tcp") && strcmp(argv[1], "udp"))) return 2;
    char *end = NULL;
    long port = strtol(argv[2], &end, 10);
    if (end == argv[2] || *end || port < 1024 || port > 65535) return 2;
    int udp = !strcmp(argv[1], "udp");
    struct sockaddr_in target = {.sin_family=AF_INET, .sin_port=htons((uint16_t)port)};
    struct in_addr mesh, clash;
    if (inet_pton(AF_INET, TARGET, &target.sin_addr) != 1 ||
        inet_pton(AF_INET, "10.126.0.2", &mesh) != 1 ||
        inet_pton(AF_INET, "172.19.0.1", &clash) != 1) return 2;
    int attempts=0, received=0, blocked=0, wrong=0, invalid=0, clash_source=0, other=0;
    int64_t start=now_ms(), finish=start+DURATION;
    while (now_ms() < finish && attempts < 800) {
        attempts++;
        int64_t deadline=now_ms()+200;
        if (deadline > finish) deadline=finish;
        int fd=socket(AF_INET, udp ? SOCK_DGRAM : SOCK_STREAM, 0);
        int success=0;
        if (fd >= 0 && fcntl(fd, F_SETFL, O_NONBLOCK) == 0 && connected(fd, &target, deadline)) {
            struct sockaddr_in local;
            socklen_t size=sizeof(local);
            if (getsockname(fd, (void *)&local, &size) != 0) {
                wrong++; other++;
            } else if (local.sin_addr.s_addr != mesh.s_addr) {
                wrong++;
                if (local.sin_addr.s_addr == clash.s_addr) clash_source++; else other++;
            }
            char request[64];
            int n=snprintf(request, sizeof(request), "bionic-handover-%d\n", attempts);
            success=transfer(fd, udp, request, (size_t)n, deadline);
        }
        if (fd >= 0) close(fd);
        if (success == 1) {
            received++;
            if (received == 1) { puts("WATCH_READY"); fflush(stdout); }
        } else if (success < 0) invalid++;
        else blocked++;
        struct timespec pause = {.tv_sec=0, .tv_nsec=10000000};
        nanosleep(&pause, NULL);
    }
    printf("{\"attempts\":%d,\"received\":%d,\"blocked\":%d,\"wrong_source\":%d,"
           "\"clash_gateway_source\":%d,\"other_source\":%d,\"invalid_payload\":%d,\"elapsed_ms\":%lld}\n",
           attempts,received,blocked,wrong,clash_source,other,invalid,(long long)(now_ms()-start));
    return received && !wrong && !invalid ? 0 : 1;
}
