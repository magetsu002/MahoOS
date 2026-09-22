// SPDX-License-Identifier: GPL-2.0
#define _GNU_SOURCE
#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "../bpf/maho_prevention_shared.h"

static volatile sig_atomic_t running = 1;
struct context { int output; const char *boot_id; };

static void stop(int signal_number) { (void)signal_number; running = 0; }

static int event(void *opaque, void *data, size_t size)
{
    const struct maho_prevention_event *row = data;
    struct context *ctx = opaque;
    struct timespec realtime;
    char stamp[32];
    struct tm broken;
    if (size != sizeof(*row))
        return 0;
    clock_gettime(CLOCK_REALTIME, &realtime);
    gmtime_r(&realtime.tv_sec, &broken);
    strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &broken);
    if (row->event_kind == MAHO_EVENT_PROCESS) {
        dprintf(ctx->output,
            "{\"schema_version\":2,\"kind\":\"guardian-prevention-event\","
            "\"observed_at\":\"%s.%09ldZ\",\"boot_id\":\"%s\","
            "\"subject\":{\"pid\":%u,\"uid\":%u,\"start_time_ticks\":%llu,"
            "\"executable_device\":%llu,\"executable_inode\":%llu},"
            "\"target\":{\"kind\":\"process\",\"pid\":%u,\"start_time_ticks\":%llu,"
            "\"executable_device\":%llu,\"executable_inode\":%llu,\"signal\":%d},"
            "\"effect_mask\":%llu,\"operation_mask\":%llu,"
            "\"policy_reason\":\"exact_process_control_authority_missing_or_invalid\","
            "\"authority_state\":\"not-current\",\"result\":\"prevented\","
            "\"host_mutation_performed\":false,\"compromise_evidence\":false}\n",
            stamp, realtime.tv_nsec, ctx->boot_id, row->tgid, row->uid,
            (unsigned long long)row->subject_start_ticks,
            (unsigned long long)row->executable_dev, (unsigned long long)row->executable_ino,
            row->target_tgid, (unsigned long long)row->target_start_ticks,
            (unsigned long long)row->target_executable_dev,
            (unsigned long long)row->target_executable_ino, row->signal,
            (unsigned long long)row->effect_mask, (unsigned long long)row->operation_mask);
    } else {
        dprintf(ctx->output,
            "{\"schema_version\":1,\"kind\":\"guardian-prevention-event\","
            "\"observed_at\":\"%s.%09ldZ\",\"boot_id\":\"%s\","
            "\"subject\":{\"pid\":%u,\"uid\":%u,\"start_time_ticks\":%llu,"
            "\"executable_device\":%llu,\"executable_inode\":%llu},"
            "\"target\":{\"device\":%llu,\"inode\":%llu,\"scope_device\":%llu,\"scope_inode\":%llu},"
            "\"effect_mask\":%llu,\"operation_mask\":%llu,"
            "\"policy_reason\":\"exact_mutation_authority_missing_or_invalid\","
            "\"authority_state\":\"not-current\",\"result\":\"prevented\","
            "\"host_mutation_performed\":false,\"compromise_evidence\":false}\n",
            stamp, realtime.tv_nsec, ctx->boot_id, row->tgid, row->uid,
            (unsigned long long)row->subject_start_ticks,
            (unsigned long long)row->executable_dev, (unsigned long long)row->executable_ino,
            (unsigned long long)row->target_dev, (unsigned long long)row->target_ino,
            (unsigned long long)row->scope_dev, (unsigned long long)row->scope_ino,
            (unsigned long long)row->effect_mask, (unsigned long long)row->operation_mask);
    }
    fsync(ctx->output);
    return 0;
}

int main(int argc, char **argv)
{
    struct ring_buffer *ring = NULL;
    struct context ctx;
    int map_fd, result = 1;
    if (argc != 4) {
        fprintf(stderr, "usage: %s RINGBUF_MAP OUTPUT_JSONL BOOT_ID\n", argv[0]);
        return 2;
    }
    map_fd = bpf_obj_get(argv[1]);
    if (map_fd < 0) {
        fprintf(stderr, "cannot open prevention event map: %s\n", strerror(errno));
        return 1;
    }
    ctx.output = open(argv[2], O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0644);
    ctx.boot_id = argv[3];
    if (ctx.output < 0) {
        fprintf(stderr, "cannot open prevention evidence: %s\n", strerror(errno));
        goto out;
    }
    ring = ring_buffer__new(map_fd, event, &ctx, NULL);
    if (!ring) {
        fprintf(stderr, "cannot create prevention ring reader: %s\n", strerror(errno));
        goto out;
    }
    signal(SIGINT, stop);
    signal(SIGTERM, stop);
    while (running) {
        int polled = ring_buffer__poll(ring, 1000);
        if (polled < 0 && polled != -EINTR) {
            fprintf(stderr, "prevention evidence poll failed: %d\n", polled);
            goto out;
        }
    }
    result = 0;
out:
    ring_buffer__free(ring);
    if (ctx.output >= 0)
        close(ctx.output);
    close(map_fd);
    return result;
}
