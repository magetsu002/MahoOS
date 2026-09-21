#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/bpf.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/mount.h>
#include <sys/sysmacros.h>
#include <time.h>
#include <unistd.h>

#include "../../bpf/maho_prevention_shared.h"

static int obj_get(const char *path)
{
    union bpf_attr attr = {};
    attr.pathname = (__u64)path;
    return syscall(SYS_bpf, BPF_OBJ_GET, &attr, sizeof(attr));
}

static int process_key(pid_t pid, struct maho_process_key *key)
{
    struct stat executable;
    FILE *stat_file;
    char path[64], buffer[4096], *cursor;
    int field = 1;
    memset(key, 0, sizeof(*key));
    snprintf(path, sizeof(path), "/proc/%d/stat", pid);
    stat_file = fopen(path, "r");
    if (!stat_file || !fgets(buffer, sizeof(buffer), stat_file))
        return 1;
    fclose(stat_file);
    cursor = strrchr(buffer, ')');
    if (!cursor)
        return 1;
    cursor += 2;
    for (char *token = strtok(cursor, " "); token; token = strtok(NULL, " "), field++)
        if (field == 20) { key->start_ticks = strtoull(token, NULL, 10); break; }
    snprintf(path, sizeof(path), "/proc/%d/exe", pid);
    if (!key->start_ticks || stat(path, &executable))
        return 1;
    key->tgid = pid;
    key->executable_dev = executable.st_dev;
    key->executable_ino = executable.st_ino;
    return 0;
}

static int grant(const char *target, int expired, int wrong_start)
{
    int map_fd = obj_get("/sys/fs/bpf/maho-prevention/maps/mutation_authorities");
    struct maho_authority_key key = {};
    struct maho_authority_value value = {};
    struct stat executable, object;
    struct timespec now;
    FILE *stat_file;
    char buffer[4096], *cursor;
    int field = 1;
    if (map_fd < 0 || stat("/proc/self/exe", &executable) || lstat(target, &object))
        return 1;
    stat_file = fopen("/proc/self/stat", "r");
    if (!stat_file || !fgets(buffer, sizeof(buffer), stat_file))
        return 1;
    fclose(stat_file);
    cursor = strrchr(buffer, ')');
    if (!cursor)
        return 1;
    cursor += 2;
    for (char *token = strtok(cursor, " "); token; token = strtok(NULL, " "), field++)
        if (field == 20) { key.start_ticks = strtoull(token, NULL, 10); break; }
    key.tgid = getpid();
    if (wrong_start)
        key.start_ticks++;
    key.executable_dev = executable.st_dev;
    key.executable_ino = executable.st_ino;
    key.scope_dev = object.st_dev;
    key.scope_ino = object.st_ino;
    clock_gettime(CLOCK_BOOTTIME, &now);
    __u64 now_ns = (__u64)now.tv_sec * 1000000000ULL + now.tv_nsec;
    value.expires_boot_ns = expired ? now_ns - 1 : now_ns + 5000000000ULL;
    value.effect_mask = 1;
    value.operation_mask = MAHO_OP_WRITE | MAHO_OP_SETATTR;
    int result = syscall(SYS_bpf, BPF_MAP_UPDATE_ELEM, &(union bpf_attr){
        .map_fd = map_fd, .key = (__u64)&key, .value = (__u64)&value, .flags = BPF_ANY,
    }, sizeof(union bpf_attr));
    if (result) perror("authority map update");
    return result;
}

static int grant_device(const char *target)
{
    int map_fd = obj_get("/sys/fs/bpf/maho-prevention/maps/device_authorities");
    struct maho_device_authority_key key = {};
    struct maho_authority_value value = {};
    struct stat executable, object;
    struct timespec now;
    FILE *stat_file;
    char buffer[4096], *cursor;
    int field = 1;
    if (map_fd < 0 || stat("/proc/self/exe", &executable) || stat(target, &object) || !S_ISBLK(object.st_mode))
        return 1;
    stat_file = fopen("/proc/self/stat", "r");
    if (!stat_file || !fgets(buffer, sizeof(buffer), stat_file))
        return 1;
    fclose(stat_file);
    cursor = strrchr(buffer, ')');
    if (!cursor)
        return 1;
    cursor += 2;
    for (char *token = strtok(cursor, " "); token; token = strtok(NULL, " "), field++)
        if (field == 20) { key.start_ticks = strtoull(token, NULL, 10); break; }
    key.tgid = getpid();
    key.executable_dev = executable.st_dev;
    key.executable_ino = executable.st_ino;
    key.device = ((__u64)major(object.st_rdev) << 20) | minor(object.st_rdev);
    clock_gettime(CLOCK_BOOTTIME, &now);
    value.expires_boot_ns = (__u64)now.tv_sec * 1000000000ULL + now.tv_nsec + 5000000000ULL;
    value.effect_mask = 1;
    value.operation_mask = MAHO_OP_DEVICE;
    union bpf_attr update_attr = {};
    update_attr.map_fd = map_fd;
    update_attr.key = (__u64)&key;
    update_attr.value = (__u64)&value;
    update_attr.flags = BPF_ANY;
    int result = syscall(SYS_bpf, BPF_MAP_UPDATE_ELEM, &update_attr, sizeof(update_attr));
    if (result) perror("device authority map update");
    return result;
}

static int register_process(pid_t pid, __u64 effect)
{
    int map_fd = obj_get("/sys/fs/bpf/maho-prevention/maps/protected_processes");
    struct maho_process_key key = {};
    struct maho_protected_value value = {.effect_mask = effect};
    union bpf_attr update = {};
    if (map_fd < 0 || process_key(pid, &key))
        return 1;
    update.map_fd = map_fd;
    update.key = (__u64)&key;
    update.value = (__u64)&value;
    update.flags = BPF_ANY;
    int result = syscall(SYS_bpf, BPF_MAP_UPDATE_ELEM, &update, sizeof(update));
    if (result) perror("protected process map update");
    close(map_fd);
    return result;
}

static int grant_signal(pid_t target_pid, int sig, int expired, int wrong_start, int wrong_signal)
{
    int map_fd = obj_get("/sys/fs/bpf/maho-prevention/maps/process_control_authorities");
    struct maho_process_authority_key key = {};
    struct maho_process_authority_value value = {};
    struct timespec now;
    union bpf_attr update = {};
    if (map_fd < 0 || process_key(getpid(), &key.subject) || process_key(target_pid, &key.target))
        return 1;
    if (wrong_start)
        key.target.start_ticks++;
    clock_gettime(CLOCK_BOOTTIME, &now);
    __u64 now_ns = (__u64)now.tv_sec * 1000000000ULL + now.tv_nsec;
    value.expires_boot_ns = expired ? now_ns - 1 : now_ns + 5000000000ULL;
    value.effect_mask = 2;
    int granted_sig = wrong_signal ? (sig == 9 ? 15 : 9) : sig;
    value.signal_mask = 1ULL << (granted_sig - 1);
    update.map_fd = map_fd;
    update.key = (__u64)&key;
    update.value = (__u64)&value;
    update.flags = BPF_ANY;
    int result = syscall(SYS_bpf, BPF_MAP_UPDATE_ELEM, &update, sizeof(update));
    if (result) perror("process authority map update");
    close(map_fd);
    return result;
}

static int write_target(const char *path)
{
    int fd = open(path, O_WRONLY | O_TRUNC | O_CREAT, 0600);
    if (fd < 0)
        return 1;
    int result = write(fd, "changed\n", 8) == 8 ? 0 : 1;
    close(fd);
    return result;
}

static int write_device(const char *path)
{
    int fd = open(path, O_WRONLY);
    if (fd < 0)
        return 1;
    int result = write(fd, "M", 1) == 1 ? 0 : 1;
    close(fd);
    return result;
}

static int churn(const char *directory, int count)
{
    char path[512];
    struct timespec begin, end;
    clock_gettime(CLOCK_MONOTONIC, &begin);
    for (int index = 0; index < count; index++) {
        snprintf(path, sizeof(path), "%s/item-%d", directory, index);
        int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        if (fd < 0 || write(fd, "x", 1) != 1 || close(fd) || unlink(path))
            return 1;
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    long long ns = (end.tv_sec - begin.tv_sec) * 1000000000LL + end.tv_nsec - begin.tv_nsec;
    printf("MAHO_PREVENTION_BENCH_NS:%lld\n", ns);
    return 0;
}

static int setup(void)
{
    mkdir("/sys/fs/bpf", 0755);
    if (mount("proc", "/proc", "proc", 0, NULL)) { perror("mount proc"); return 11; }
    if (mount("sysfs", "/sys", "sysfs", 0, NULL)) { perror("mount sysfs"); return 12; }
    if (mount("devtmpfs", "/dev", "devtmpfs", 0, NULL)) { perror("mount devtmpfs"); return 14; }
    mkdir("/sys/fs/bpf", 0755);
    if (mount("bpf", "/sys/fs/bpf", "bpf", 0, NULL)) { perror("mount bpf"); return 13; }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "setup")) return setup();
    if (argc == 2 && !strcmp(argv[1], "protected-loop")) {
        for (;;) pause();
    }
    if (argc < 3)
        return 2;
    if (!strcmp(argv[1], "write")) return write_target(argv[2]);
    if (!strcmp(argv[1], "register-process") && argc == 4)
        return register_process((pid_t)atoi(argv[2]), strtoull(argv[3], NULL, 0));
    if (!strcmp(argv[1], "signal") && argc == 4)
        return kill((pid_t)atoi(argv[2]), atoi(argv[3])) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "authorized-signal") && argc == 4)
        return grant_signal((pid_t)atoi(argv[2]), atoi(argv[3]), 0, 0, 0)
            || (kill((pid_t)atoi(argv[2]), atoi(argv[3])) == 0 ? 0 : 1);
    if (!strcmp(argv[1], "expired-signal") && argc == 4)
        return grant_signal((pid_t)atoi(argv[2]), atoi(argv[3]), 1, 0, 0)
            || (kill((pid_t)atoi(argv[2]), atoi(argv[3])) == 0 ? 0 : 1);
    if (!strcmp(argv[1], "wrong-start-signal") && argc == 4)
        return grant_signal((pid_t)atoi(argv[2]), atoi(argv[3]), 0, 1, 0)
            || (kill((pid_t)atoi(argv[2]), atoi(argv[3])) == 0 ? 0 : 1);
    if (!strcmp(argv[1], "wrong-signal-authority") && argc == 4)
        return grant_signal((pid_t)atoi(argv[2]), atoi(argv[3]), 0, 0, 1)
            || (kill((pid_t)atoi(argv[2]), atoi(argv[3])) == 0 ? 0 : 1);
    if (!strcmp(argv[1], "device-write")) return write_device(argv[2]);
    if (!strcmp(argv[1], "authorized-device-write")) return grant_device(argv[2]) || write_device(argv[2]);
    if (!strcmp(argv[1], "device-alias")) {
        struct stat object;
        if (stat(argv[2], &object) || !S_ISBLK(object.st_mode)) return 1;
        unlink("/ordinary/device-alias");
        if (mknod("/ordinary/device-alias", S_IFBLK | 0600, object.st_rdev)) return 1;
        return write_device("/ordinary/device-alias");
    }
    if (!strcmp(argv[1], "authorized-write")) return grant(argv[2], 0, 0) || write_target(argv[2]);
    if (!strcmp(argv[1], "expired-write")) return grant(argv[2], 1, 0) || write_target(argv[2]);
    if (!strcmp(argv[1], "wrong-start-write")) return grant(argv[2], 0, 1) || write_target(argv[2]);
    if (!strcmp(argv[1], "scope-escape") && argc == 4) return grant(argv[2], 0, 0) || write_target(argv[3]);
    if (!strcmp(argv[1], "unlink")) return unlink(argv[2]) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "chmod")) return chmod(argv[2], 0777) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "rename") && argc == 4) return rename(argv[2], argv[3]) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "hardlink") && argc == 4) return link(argv[2], argv[3]) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "symlink") && argc == 4) return symlink(argv[2], argv[3]) == 0 ? 0 : 1;
    if (!strcmp(argv[1], "churn")) return churn(argv[2], atoi(argv[3]));
    if (!strcmp(argv[1], "bind") && argc == 4) {
        mkdir(argv[3], 0755);
        return mount(argv[2], argv[3], NULL, MS_BIND, NULL) == 0 ? 0 : 1;
    }
    if (!strcmp(argv[1], "namespace-write") && argc == 4) {
        if (unshare(CLONE_NEWNS) || mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL)) return 1;
        mkdir(argv[3], 0755);
        if (mount(argv[2], argv[3], NULL, MS_BIND, NULL)) return 1;
        char path[512]; snprintf(path, sizeof(path), "%s/critical", argv[3]);
        return write_target(path);
    }
    return 2;
}
