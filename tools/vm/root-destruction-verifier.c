// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

struct protected_file {
    const char *live;
    const char *before;
    const char *after;
};

static int copy_file(const char *source, const char *destination)
{
    char buffer[65536];
    ssize_t n;
    int in = open(source, O_RDONLY | O_CLOEXEC);
    int out;
    if (in < 0)
        return -1;
    out = open(destination, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (out < 0) {
        close(in);
        return -1;
    }
    while ((n = read(in, buffer, sizeof(buffer))) > 0) {
        ssize_t offset = 0;
        while (offset < n) {
            ssize_t written = write(out, buffer + offset, (size_t)(n - offset));
            if (written <= 0) {
                close(in);
                close(out);
                return -1;
            }
            offset += written;
        }
    }
    if (n < 0 || fsync(out) != 0) {
        close(in);
        close(out);
        return -1;
    }
    close(in);
    return close(out);
}

static bool files_equal(const char *left, const char *right)
{
    unsigned char a[65536], b[65536];
    int fa = open(left, O_RDONLY | O_CLOEXEC);
    int fb = open(right, O_RDONLY | O_CLOEXEC);
    bool equal = false;
    if (fa < 0 || fb < 0)
        goto out;
    for (;;) {
        ssize_t na = read(fa, a, sizeof(a));
        ssize_t nb = read(fb, b, sizeof(b));
        if (na < 0 || nb < 0 || na != nb)
            goto out;
        if (na == 0) {
            equal = true;
            goto out;
        }
        if (memcmp(a, b, (size_t)na) != 0)
            goto out;
    }
out:
    if (fa >= 0)
        close(fa);
    if (fb >= 0)
        close(fb);
    return equal;
}

static bool path_is_file(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0 && S_ISREG(st.st_mode) && st.st_size > 0;
}

static bool path_is_dir(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static bool path_is_symlink(const char *path)
{
    struct stat st;
    return lstat(path, &st) == 0 && S_ISLNK(st.st_mode);
}

static bool evidence_has_rm_prevention(const char *path, unsigned long long rm_inode)
{
    char *data = NULL;
    struct stat st;
    int fd = -1;
    bool found = false;
    char inode_marker[96];
    if (stat(path, &st) != 0 || st.st_size <= 0 || st.st_size > 128 * 1024 * 1024)
        return false;
    data = calloc(1, (size_t)st.st_size + 1);
    if (!data)
        return false;
    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        goto out;
    size_t offset = 0;
    while (offset < (size_t)st.st_size) {
        ssize_t n = read(fd, data + offset, (size_t)st.st_size - offset);
        if (n <= 0)
            goto out;
        offset += (size_t)n;
    }
    snprintf(inode_marker, sizeof(inode_marker),
             "\"executable_inode\":%llu", rm_inode);
    if (strstr(data, "\"result\":\"prevented\"") &&
        strstr(data, "\"host_mutation_performed\":false") &&
        strstr(data, inode_marker))
        found = true;
out:
    if (fd >= 0)
        close(fd);
    free(data);
    return found;
}

static int durable_printf(const char *path, const char *format, ...)
{
    va_list args;
    FILE *stream = fopen(path, "w");
    int rc;
    if (!stream)
        return -1;
    va_start(args, format);
    rc = vfprintf(stream, format, args);
    va_end(args);
    if (rc < 0 || fflush(stream) != 0 || fsync(fileno(stream)) != 0) {
        fclose(stream);
        return -1;
    }
    return fclose(stream);
}

static uint64_t realtime_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) != 0)
        return 0;
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

int main(int argc, char **argv)
{
    const char *directory;
    const char *revision;
    const char *events;
    const char *runtime_target;
    const char *runtime_link_target;
    unsigned long long rm_inode;
    pid_t attack_pid, evidence_pid;
    int rm_exit = 127, attack_status = 0;
    bool attack_bounded = false;
    uint64_t start_ns, end_ns;
    char path[4096];
    char before_root[4096], after_root[4096];
    char runtime_manifest[4096];
    char runtime_before[8192], runtime_after[8192];
    const char *reason = NULL;
    bool fixture_deleted, protected_usr, protected_etc, protected_boot;
    bool protected_pacman, protected_runtime, bytes_unchanged = true;
    bool prevention_evidence;
    struct protected_file files[5];

    if (argc != 10) {
        dprintf(STDERR_FILENO,
                "usage: %s DIRECTORY REVISION START_NS ATTACK_PID EVIDENCE_PID EVENTS RM_INODE RUNTIME_TARGET RUNTIME_LINK_TARGET\n",
                argv[0]);
        return 2;
    }
    directory = argv[1];
    revision = argv[2];
    start_ns = strtoull(argv[3], NULL, 10);
    attack_pid = (pid_t)strtol(argv[4], NULL, 10);
    evidence_pid = (pid_t)strtol(argv[5], NULL, 10);
    events = argv[6];
    rm_inode = strtoull(argv[7], NULL, 10);
    runtime_target = argv[8];
    runtime_link_target = argv[9];

    snprintf(before_root, sizeof(before_root), "%s/evidence/protected-before", directory);
    snprintf(after_root, sizeof(after_root), "%s/evidence/protected-after", directory);
    snprintf(runtime_manifest, sizeof(runtime_manifest), "%s/manifest.json", runtime_target);
    snprintf(runtime_before, sizeof(runtime_before), "%s/runtime-manifest", before_root);
    snprintf(runtime_after, sizeof(runtime_after), "%s/runtime-manifest", after_root);
    static char before_paths[4][8192];
    static char after_paths[4][8192];
    const char *names[4] = {"usr-bash", "etc-passwd", "boot-kernel", "pacman-db-version"};
    const char *live[4] = {
        "/usr/bin/bash",
        "/etc/passwd",
        "/boot/vmlinuz-linux-cachyos",
        "/var/lib/pacman/local/ALPM_DB_VERSION"
    };
    for (size_t i = 0; i < 4; ++i) {
        snprintf(before_paths[i], sizeof(before_paths[i]), "%s/%s", before_root, names[i]);
        snprintf(after_paths[i], sizeof(after_paths[i]), "%s/%s", after_root, names[i]);
        files[i] = (struct protected_file){live[i], before_paths[i], after_paths[i]};
    }
    files[4] = (struct protected_file){runtime_manifest, runtime_before, runtime_after};

    /*
     * This static verifier is the independent control plane.  The real rm
     * process is already running when the shell execs us, so verification no
     * longer depends on attacked userspace returning from a huge protected
     * tree walk.  We require proof that rm both destroyed deliberately
     * unprotected root state and generated an attributable prevention event.
     * Once both facts are durable, bound the still-running traversal.
     */
    for (int attempt = 0; attempt < 1200; ++attempt) {
        pid_t waited = waitpid(attack_pid, &attack_status, WNOHANG);
        bool fixture_gone =
            access("/var/tmp/maho-root-unprotected/proof", F_OK) != 0 && errno == ENOENT;
        bool prevented = evidence_has_rm_prevention(events, rm_inode);
        if (waited == attack_pid)
            break;
        if (waited < 0 && errno != EINTR)
            break;
        if (fixture_gone && prevented) {
            if (kill(attack_pid, SIGKILL) == 0 || errno == ESRCH)
                attack_bounded = true;
            while (waitpid(attack_pid, &attack_status, 0) < 0 && errno == EINTR)
                ;
            break;
        }
        struct timespec pause = {.tv_sec = 0, .tv_nsec = 100000000L};
        nanosleep(&pause, NULL);
    }
    if (waitpid(attack_pid, &attack_status, WNOHANG) == 0) {
        kill(attack_pid, SIGKILL);
        while (waitpid(attack_pid, &attack_status, 0) < 0 && errno == EINTR)
            ;
    }
    {
        struct timespec flush_pause = {.tv_sec = 0, .tv_nsec = 250000000L};
        nanosleep(&flush_pause, NULL);
    }
    kill(evidence_pid, SIGTERM);
    while (waitpid(evidence_pid, NULL, 0) < 0 && errno == EINTR)
        ;

    if (WIFEXITED(attack_status))
        rm_exit = WEXITSTATUS(attack_status);
    else if (WIFSIGNALED(attack_status))
        rm_exit = 128 + WTERMSIG(attack_status);

    fixture_deleted = access("/var/tmp/maho-root-unprotected/proof", F_OK) != 0 && errno == ENOENT;
    protected_usr = access("/usr/bin/bash", X_OK) == 0;
    protected_etc = path_is_file("/etc/passwd");
    protected_boot = path_is_file("/boot/vmlinuz-linux-cachyos");
    protected_pacman = path_is_dir("/var/lib/pacman/local") &&
                       path_is_file("/var/lib/pacman/local/ALPM_DB_VERSION");
    char link_value[4096];
    ssize_t link_size = readlink("/home/mahovm/.local/share/maho/runtime/current",
                                 link_value, sizeof(link_value) - 1);
    if (link_size >= 0)
        link_value[link_size] = '\0';
    protected_runtime = path_is_symlink("/home/mahovm/.local/share/maho/runtime/current") &&
                        link_size >= 0 && strcmp(link_value, runtime_link_target) == 0 &&
                        path_is_file(runtime_manifest);

    if (mkdir(after_root, 0755) != 0 && errno != EEXIST)
        bytes_unchanged = false;
    for (size_t i = 0; i < 5; ++i) {
        if (copy_file(files[i].live, files[i].after) != 0 ||
            !files_equal(files[i].before, files[i].after))
            bytes_unchanged = false;
    }

    prevention_evidence = evidence_has_rm_prevention(events, rm_inode);
    if (rm_exit == 127)
        reason = "real rm-style attack failed to execute";
    else if (WIFSIGNALED(attack_status) && !attack_bounded)
        reason = "external control plane timed out before independent attack proof completed";
    else if (!fixture_deleted)
        reason = "rm-style root attack did not destroy deliberately unprotected root state";
    else if (!protected_usr)
        reason = "protected /usr state did not survive";
    else if (!protected_etc)
        reason = "protected /etc state did not survive";
    else if (!protected_boot)
        reason = "protected /boot state did not survive";
    else if (!protected_pacman)
        reason = "protected pacman authority did not survive";
    else if (!protected_runtime)
        reason = "protected Maho runtime did not survive";
    else if (!bytes_unchanged)
        reason = "protected state changed during rm-style attack";
    else if (!prevention_evidence)
        reason = "Prevention Boundary evidence for the rm process was not persisted";

    bool passed = reason == NULL;
    end_ns = realtime_ns();

    snprintf(path, sizeof(path), "%s/evidence/root-destruction-result.json", directory);
    if (durable_printf(path,
        "{\n"
        "  \"schema_version\": 1,\n"
        "  \"attack_executed\": %s,\n"
        "  \"rm_exit\": %d,\n"
        "  \"rm_executable_inode\": %llu,\n"
        "  \"external_control_plane_bounded_traversal\": %s,\n"
        "  \"unprotected_fixture_deleted\": %s,\n"
        "  \"protected_usr\": %s,\n"
        "  \"protected_etc\": %s,\n"
        "  \"protected_boot\": %s,\n"
        "  \"protected_pacman\": %s,\n"
        "  \"protected_runtime\": %s,\n"
        "  \"protected_bytes_unchanged\": %s,\n"
        "  \"prevention_evidence\": %s,\n"
        "  \"durable_sink\": \"maho_evidence_9p\",\n"
        "  \"host_mutation_performed\": false,\n"
        "  \"pass\": %s\n"
        "}\n",
        (rm_exit != 127 && fixture_deleted) ? "true" : "false",
        rm_exit, rm_inode,
        attack_bounded ? "true" : "false",
        fixture_deleted ? "true" : "false",
        protected_usr ? "true" : "false",
        protected_etc ? "true" : "false",
        protected_boot ? "true" : "false",
        protected_pacman ? "true" : "false",
        protected_runtime ? "true" : "false",
        bytes_unchanged ? "true" : "false",
        prevention_evidence ? "true" : "false",
        passed ? "true" : "false") != 0)
        passed = false;
    snprintf(path, sizeof(path), "%s/summary.json", directory);
    durable_printf(path,
        "{\n"
        "  \"schema_version\": 1,\n"
        "  \"source_revision\": \"%s\",\n"
        "  \"scenario\": \"full-disposable-root-destruction\",\n"
        "  \"iteration\": 1,\n"
        "  \"expected_outcome\": \"PREVENTED\",\n"
        "  \"actual_outcome\": \"%s\",\n"
        "  \"start_time_ns\": %llu,\n"
        "  \"end_time_ns\": %llu,\n"
        "  \"detection_latency_ms\": null,\n"
        "  \"recovery_latency_ms\": null,\n"
        "  \"convergence_latency_ms\": null,\n"
        "  \"incidents_before\": null,\n"
        "  \"incidents_after\": null,\n"
        "  \"host_mutation_performed\": false,\n"
        "  \"guest_root_mutation_performed\": %s,\n"
        "  \"protected_effect_blocked\": %s,\n"
        "  \"manual_intervention_required\": false,\n"
        "  \"pass\": %s,\n"
        "  \"failure_reason\": %s%s%s\n"
        "}\n",
        revision, passed ? "PREVENTED" : "BUG",
        (unsigned long long)start_ns, (unsigned long long)end_ns,
        fixture_deleted ? "true" : "false",
        prevention_evidence ? "true" : "false",
        passed ? "true" : "false",
        reason ? "\"" : "", reason ? reason : "null", reason ? "\"" : "");

    snprintf(path, sizeof(path), "%s/../../../summary.json", directory);
    double duration = start_ns && end_ns > start_ns ?
        (double)(end_ns - start_ns) / 1000000000.0 : 0.0;
    durable_printf(path,
        "{\n"
        "  \"schema_version\": 1,\n"
        "  \"profile\": \"torture-root-destruction\",\n"
        "  \"source_revision\": \"%s\",\n"
        "  \"status\": \"%s\",\n"
        "  \"exit_code\": %d,\n"
        "  \"duration_seconds\": %.3f,\n"
        "  \"scenario_count\": 1,\n"
        "  \"outcomes\": {\"%s\": 1}\n"
        "}\n",
        revision, passed ? "passed" : "failed", passed ? 0 : 1, duration,
        passed ? "PREVENTED" : "BUG");

    dprintf(passed ? STDOUT_FILENO : STDERR_FILENO,
            "%s  torture scenario=full-disposable-root-destruction outcome=%s%s%s\n",
            passed ? "PASS" : "FAIL", passed ? "PREVENTED" : "BUG",
            reason ? " reason=" : "", reason ? reason : "");
    sync();
    return passed ? 0 : 1;
}
