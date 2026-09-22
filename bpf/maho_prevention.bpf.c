// SPDX-License-Identifier: GPL-2.0
/* Kernel-enforced target/effect boundary.  No command names are inspected. */
#include <linux/bpf.h>
#include <linux/errno.h>
#include <linux/fcntl.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_core_read.h>
#include <bpf/bpf_tracing.h>

#include "maho_prevention_shared.h"

typedef unsigned int dev_t;
typedef unsigned short umode_t;

struct super_block { dev_t s_dev; } __attribute__((preserve_access_index));
struct inode {
    umode_t i_mode;
    struct super_block *i_sb;
    __u64 i_ino;
    dev_t i_rdev;
} __attribute__((preserve_access_index));
struct dentry {
    struct dentry *d_parent;
    struct inode *d_inode;
} __attribute__((preserve_access_index));
struct vfsmount;
struct path { struct vfsmount *mnt; struct dentry *dentry; } __attribute__((preserve_access_index));
struct file {
    unsigned int f_flags;
    struct path f_path;
} __attribute__((preserve_access_index));
struct mm_struct { struct file *exe_file; } __attribute__((preserve_access_index));
struct task_struct {
    struct mm_struct *mm;
    struct task_struct *group_leader;
    __u64 start_boottime;
    int tgid;
} __attribute__((preserve_access_index));
struct iattr;
struct mnt_idmap;
struct kernel_siginfo;
struct cred;

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 65536);
    __type(key, struct maho_object_key);
    __type(value, struct maho_protected_value);
} protected_objects SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 64);
    __type(key, __u64);
    __type(value, struct maho_protected_value);
} protected_devices SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 16384);
    __type(key, struct maho_authority_key);
    __type(value, struct maho_authority_value);
} mutation_authorities SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 256);
    __type(key, struct maho_device_authority_key);
    __type(value, struct maho_authority_value);
} device_authorities SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 4096);
    __type(key, struct maho_process_key);
    __type(value, struct maho_protected_value);
} protected_processes SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 4096);
    __type(key, struct maho_process_authority_key);
    __type(value, struct maho_process_authority_value);
} process_control_authorities SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u32);
} enforcement_state SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 20);
} prevention_events SEC(".maps");

static __always_inline int active(void)
{
    __u32 key = 0;
    __u32 *value = bpf_map_lookup_elem(&enforcement_state, &key);
    return value && *value == 1;
}

static __always_inline int inode_key(struct inode *inode, struct maho_object_key *key)
{
    struct super_block *sb;
    if (!inode)
        return -1;
    sb = BPF_CORE_READ(inode, i_sb);
    if (!sb)
        return -1;
    key->dev = BPF_CORE_READ(sb, s_dev);
    key->ino = BPF_CORE_READ(inode, i_ino);
    return 0;
}

static __always_inline int process_key_from_task(
    struct task_struct *task, struct maho_process_key *key)
{
    struct task_struct *leader;
    struct mm_struct *mm;
    struct file *exe;
    struct dentry *dentry;
    struct inode *inode;
    struct maho_object_key executable = {};

    if (!task)
        return -1;
    leader = BPF_CORE_READ(task, group_leader);
    if (!leader)
        leader = task;
    key->tgid = (__u32)BPF_CORE_READ(leader, tgid);
    key->start_ticks = BPF_CORE_READ(leader, start_boottime) / 10000000ULL;
    mm = BPF_CORE_READ(leader, mm);
    if (!mm)
        return -1;
    exe = BPF_CORE_READ(mm, exe_file);
    if (!exe)
        return -1;
    dentry = BPF_CORE_READ(exe, f_path.dentry);
    inode = dentry ? BPF_CORE_READ(dentry, d_inode) : 0;
    if (inode_key(inode, &executable) != 0)
        return -1;
    key->executable_dev = executable.dev;
    key->executable_ino = executable.ino;
    return 0;
}

static __always_inline struct maho_protected_value *scope_for_dentry(
    struct dentry *dentry, struct maho_object_key *scope)
{
    struct dentry *cursor = dentry;
    struct dentry *parent;
    struct inode *inode;
    struct maho_protected_value *value;

#pragma unroll
    for (int depth = 0; depth < 12; depth++) {
        if (!cursor)
            break;
        inode = BPF_CORE_READ(cursor, d_inode);
        if (inode && inode_key(inode, scope) == 0) {
            value = bpf_map_lookup_elem(&protected_objects, scope);
            if (value && (depth == 0 || (value->flags & MAHO_SCOPE_RECURSIVE)))
                return value;
        }
        parent = BPF_CORE_READ(cursor, d_parent);
        if (!parent || parent == cursor)
            break;
        cursor = parent;
    }
    return 0;
}

static __always_inline struct maho_protected_value *scope_for_inode(
    struct inode *inode, struct maho_object_key *scope)
{
    if (inode_key(inode, scope) != 0)
        return 0;
    return bpf_map_lookup_elem(&protected_objects, scope);
}

static __always_inline int authority_for_object(
    struct maho_authority_key *key, const struct maho_object_key *object,
    __u64 effect, __u64 operation)
{
    struct maho_authority_value *value;
    key->scope_dev = object->dev;
    key->scope_ino = object->ino;
    value = bpf_map_lookup_elem(&mutation_authorities, key);
    if (!value || bpf_ktime_get_boot_ns() >= value->expires_boot_ns)
        return 0;
    return (value->effect_mask & effect) && (value->operation_mask & operation);
}

static __always_inline int exact_authority(
    struct dentry *target_dentry, struct inode *target_inode,
    __u64 effect, __u64 operation)
{
    struct maho_authority_key key = {};
    struct task_struct *task;
    struct mm_struct *mm;
    struct file *exe;
    struct dentry *dentry;
    struct dentry *parent;
    struct inode *inode;
    struct maho_object_key executable = {}, object = {};

    key.tgid = bpf_get_current_pid_tgid() >> 32;
    task = (struct task_struct *)bpf_get_current_task_btf();
    key.start_ticks = BPF_CORE_READ(task, start_boottime) / 10000000ULL;
    mm = BPF_CORE_READ(task, mm);
    if (!mm)
        return 0;
    exe = BPF_CORE_READ(mm, exe_file);
    if (!exe)
        return 0;
    dentry = BPF_CORE_READ(exe, f_path.dentry);
    inode = dentry ? BPF_CORE_READ(dentry, d_inode) : 0;
    if (inode_key(inode, &executable) != 0)
        return 0;
    key.executable_dev = executable.dev;
    key.executable_ino = executable.ino;
    if (!target_dentry)
        return inode_key(target_inode, &object) == 0
            && authority_for_object(&key, &object, effect, operation);
#pragma unroll
    for (int depth = 0; depth < 12; depth++) {
        if (!target_dentry)
            break;
        inode = BPF_CORE_READ(target_dentry, d_inode);
        if (inode && inode_key(inode, &object) == 0
            && authority_for_object(&key, &object, effect, operation))
            return 1;
        parent = BPF_CORE_READ(target_dentry, d_parent);
        if (!parent || parent == target_dentry)
            break;
        target_dentry = parent;
    }
    return 0;
}

static __always_inline int deny_with_evidence(
    const struct maho_object_key *target, const struct maho_object_key *scope,
    __u64 effect, __u64 operation)
{
    struct maho_prevention_event *event;
    struct task_struct *task;
    struct mm_struct *mm;
    struct file *exe;
    struct dentry *exe_dentry;
    struct inode *exe_inode;
    struct maho_object_key executable = {};

    event = bpf_ringbuf_reserve(&prevention_events, sizeof(*event), 0);
    if (event) {
        __builtin_memset(event, 0, sizeof(*event));
        event->timestamp_ns = bpf_ktime_get_boot_ns();
        event->target_dev = target->dev;
        event->target_ino = target->ino;
        event->scope_dev = scope->dev;
        event->scope_ino = scope->ino;
        event->effect_mask = effect;
        event->operation_mask = operation;
        task = (struct task_struct *)bpf_get_current_task_btf();
        event->subject_start_ticks = BPF_CORE_READ(task, start_boottime) / 10000000ULL;
        mm = BPF_CORE_READ(task, mm);
        exe = mm ? BPF_CORE_READ(mm, exe_file) : 0;
        exe_dentry = exe ? BPF_CORE_READ(exe, f_path.dentry) : 0;
        exe_inode = exe_dentry ? BPF_CORE_READ(exe_dentry, d_inode) : 0;
        if (inode_key(exe_inode, &executable) == 0) {
            event->executable_dev = executable.dev;
            event->executable_ino = executable.ino;
        }
        event->tgid = bpf_get_current_pid_tgid() >> 32;
        event->uid = (__u32)bpf_get_current_uid_gid();
        event->result = -EPERM;
        event->authority_state = 0;
        event->event_kind = MAHO_EVENT_OBJECT;
        bpf_ringbuf_submit(event, 0);
    }
    return -EPERM;
}

static __always_inline int enforce(
    struct dentry *dentry, struct inode *inode, __u64 operation, int previous_ret)
{
    struct maho_object_key target = {}, scope = {};
    struct maho_protected_value *protected;

    if (previous_ret)
        return previous_ret;
    if (!active())
        return 0;
    if (dentry) {
        protected = scope_for_dentry(dentry, &scope);
        inode = BPF_CORE_READ(dentry, d_inode);
    } else {
        protected = scope_for_inode(inode, &scope);
    }
    if (!protected)
        return 0;
    if (inode)
        inode_key(inode, &target);
    if (exact_authority(dentry, inode, protected->effect_mask, operation))
        return 0;
    return deny_with_evidence(&target, &scope, protected->effect_mask, operation);
}

static __always_inline int enforce_device(struct file *file, int previous_ret)
{
    struct inode *inode;
    struct maho_object_key object = {};
    struct maho_protected_value *protected;
    __u64 device;

    if (previous_ret || !active())
        return previous_ret;
    inode = BPF_CORE_READ(file, f_path.dentry, d_inode);
    if (!inode || (BPF_CORE_READ(inode, i_mode) & 0170000) != 0060000)
        return 0;
    device = BPF_CORE_READ(inode, i_rdev);
    protected = bpf_map_lookup_elem(&protected_devices, &device);
    if (!protected)
        return 0;
    object.dev = device;
    object.ino = 0;
    {
        struct maho_device_authority_key key = {};
        struct maho_authority_value *authority;
        struct task_struct *task = (struct task_struct *)bpf_get_current_task_btf();
        struct mm_struct *mm = BPF_CORE_READ(task, mm);
        struct file *exe = mm ? BPF_CORE_READ(mm, exe_file) : 0;
        struct dentry *exe_dentry = exe ? BPF_CORE_READ(exe, f_path.dentry) : 0;
        struct inode *exe_inode = exe_dentry ? BPF_CORE_READ(exe_dentry, d_inode) : 0;
        struct maho_object_key executable = {};
        key.tgid = bpf_get_current_pid_tgid() >> 32;
        key.start_ticks = BPF_CORE_READ(task, start_boottime) / 10000000ULL;
        if (inode_key(exe_inode, &executable) == 0) {
            key.executable_dev = executable.dev;
            key.executable_ino = executable.ino;
            key.device = device;
            authority = bpf_map_lookup_elem(&device_authorities, &key);
            if (authority && bpf_ktime_get_boot_ns() < authority->expires_boot_ns
                && (authority->effect_mask & protected->effect_mask)
                && (authority->operation_mask & MAHO_OP_DEVICE))
                return 1;
        }
    }
    return deny_with_evidence(&object, &object, protected->effect_mask, MAHO_OP_DEVICE);
}

static __always_inline __u64 signal_bit(int sig)
{
    if (sig <= 0 || sig > 64)
        return 0;
    return 1ULL << (sig - 1);
}

static __always_inline int deny_process_with_evidence(
    const struct maho_process_key *subject, const struct maho_process_key *target,
    __u64 effect, int sig)
{
    struct maho_prevention_event *event;
    event = bpf_ringbuf_reserve(&prevention_events, sizeof(*event), 0);
    if (event) {
        __builtin_memset(event, 0, sizeof(*event));
        event->timestamp_ns = bpf_ktime_get_boot_ns();
        event->effect_mask = effect;
        event->operation_mask = MAHO_OP_SIGNAL;
        event->subject_start_ticks = subject->start_ticks;
        event->executable_dev = subject->executable_dev;
        event->executable_ino = subject->executable_ino;
        event->tgid = subject->tgid;
        event->uid = (__u32)bpf_get_current_uid_gid();
        event->result = -EPERM;
        event->authority_state = 0;
        event->event_kind = MAHO_EVENT_PROCESS;
        event->signal = sig;
        event->target_tgid = target->tgid;
        event->target_start_ticks = target->start_ticks;
        event->target_executable_dev = target->executable_dev;
        event->target_executable_ino = target->executable_ino;
        bpf_ringbuf_submit(event, 0);
    }
    return -EPERM;
}

static __always_inline int enforce_process_control(
    struct task_struct *target_task, int sig, int previous_ret)
{
    struct maho_process_key subject = {}, target = {};
    struct maho_process_authority_key authority_key = {};
    struct maho_process_authority_value *authority;
    struct maho_protected_value *protected;
    __u64 bit;

    if (previous_ret || !active() || sig == 0)
        return previous_ret;
    bit = signal_bit(sig);
    if (!bit || process_key_from_task(target_task, &target) != 0)
        return 0;
    protected = bpf_map_lookup_elem(&protected_processes, &target);
    if (!protected)
        return 0;
    if (process_key_from_task((struct task_struct *)bpf_get_current_task_btf(), &subject) == 0) {
        authority_key.subject = subject;
        authority_key.target = target;
        authority = bpf_map_lookup_elem(&process_control_authorities, &authority_key);
        if (authority && bpf_ktime_get_boot_ns() < authority->expires_boot_ns
            && (authority->effect_mask & protected->effect_mask)
            && (authority->signal_mask & bit))
            return 0;
    }
    return deny_process_with_evidence(&subject, &target, protected->effect_mask, sig);
}

SEC("lsm/task_kill")
int BPF_PROG(maho_task_kill, struct task_struct *p, struct kernel_siginfo *info,
             int sig, const struct cred *cred, int ret)
{
    return enforce_process_control(p, sig, ret);
}

SEC("lsm/file_open")
int BPF_PROG(maho_file_open, struct file *file, int ret)
{
    unsigned int flags = BPF_CORE_READ(file, f_flags);
    if (!(flags & (O_WRONLY | O_RDWR | O_TRUNC | O_APPEND)))
        return ret;
    {
        int device_ret = enforce_device(file, ret);
        if (device_ret < 0)
            return device_ret;
        if (device_ret > 0)
            return ret;
    }
    return enforce(BPF_CORE_READ(file, f_path.dentry), 0, MAHO_OP_WRITE, ret);
}

SEC("lsm/inode_create")
int BPF_PROG(maho_inode_create, struct inode *dir, struct dentry *dentry, umode_t mode, int ret)
{ return enforce(dentry, dir, MAHO_OP_CREATE, ret); }

SEC("lsm/inode_mkdir")
int BPF_PROG(maho_inode_mkdir, struct inode *dir, struct dentry *dentry, umode_t mode, int ret)
{ return enforce(dentry, dir, MAHO_OP_CREATE, ret); }

SEC("lsm/inode_mknod")
int BPF_PROG(maho_inode_mknod, struct inode *dir, struct dentry *dentry, umode_t mode, dev_t dev, int ret)
{ return enforce(dentry, dir, MAHO_OP_CREATE, ret); }

SEC("lsm/inode_unlink")
int BPF_PROG(maho_inode_unlink, struct inode *dir, struct dentry *dentry, int ret)
{ return enforce(dentry, 0, MAHO_OP_UNLINK, ret); }

SEC("lsm/inode_rmdir")
int BPF_PROG(maho_inode_rmdir, struct inode *dir, struct dentry *dentry, int ret)
{ return enforce(dentry, 0, MAHO_OP_UNLINK, ret); }

SEC("lsm/inode_symlink")
int BPF_PROG(maho_inode_symlink, struct inode *dir, struct dentry *dentry, const char *name, int ret)
{ return enforce(dentry, dir, MAHO_OP_SYMLINK, ret); }

SEC("lsm/inode_link")
int BPF_PROG(maho_inode_link, struct dentry *old_dentry, struct inode *dir, struct dentry *new_dentry, int ret)
{
    int denied = enforce(old_dentry, 0, MAHO_OP_LINK, ret);
    return denied ? denied : enforce(new_dentry, dir, MAHO_OP_LINK, ret);
}

SEC("lsm/inode_rename")
int BPF_PROG(maho_inode_rename, struct inode *old_dir, struct dentry *old_dentry,
             struct inode *new_dir, struct dentry *new_dentry, int ret)
{
    int denied = enforce(old_dentry, 0, MAHO_OP_RENAME, ret);
    return denied ? denied : enforce(new_dentry, new_dir, MAHO_OP_RENAME, ret);
}

SEC("lsm/inode_setattr")
int BPF_PROG(maho_inode_setattr, struct mnt_idmap *idmap, struct dentry *dentry,
             struct iattr *attr, int ret)
{ return enforce(dentry, 0, MAHO_OP_SETATTR, ret); }

SEC("lsm/sb_mount")
int BPF_PROG(maho_sb_mount, const char *dev_name, const struct path *path,
             const char *type, unsigned long flags, void *data, int ret)
{ return enforce(path ? BPF_CORE_READ(path, dentry) : 0, 0, MAHO_OP_MOUNT, ret); }

char LICENSE[] SEC("license") = "GPL";
