#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glib-unix.h>
#include <gtk/gtk.h>
#include <polkit/polkit.h>
#include <polkitagent/polkitagent.h>
#include <pwd.h>
#include <signal.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define MAHO_AGENT_OBJECT_PATH "/org/maho/PolkitAgent"
#define MAHO_POLKIT_BUS_NAME "org.freedesktop.PolicyKit1"
#define MAHO_MAX_TEXT 500

typedef struct {
    PolkitIdentity *identity;
    gchar *key;
    gchar *label;
    gint uid;
    gboolean has_uid;
} IdentityChoice;

typedef struct {
    guint64 request_id;
    guint64 prompt_serial;
    guint64 responded_serial;
    gboolean awaiting;
} ResponseGate;

typedef struct _MahoPolkitListener MahoPolkitListener;
typedef struct _MahoPolkitListenerClass MahoPolkitListenerClass;

#define MAHO_TYPE_POLKIT_LISTENER (maho_polkit_listener_get_type())
#define MAHO_POLKIT_LISTENER(obj) \
    (G_TYPE_CHECK_INSTANCE_CAST((obj), MAHO_TYPE_POLKIT_LISTENER, MahoPolkitListener))

typedef struct {
    MahoPolkitListener *owner;
    GTask *task;
    GCancellable *cancellable;
    gulong cancel_id;
    PolkitAgentSession *session;
    GPtrArray *identities;
    gchar *action_id;
    gchar *message;
    gchar *cookie;
    gchar *requester;
    gchar *prompt;
    gchar *info_text;
    gchar *error_text;
    gint requester_pid;
    guint requester_watch;
    guint cancel_force_watch;
    guint selected_index;
    guint attempt;
    gboolean echo_on;
    gboolean cancel_requested;
    gboolean finished;
    ResponseGate gate;
} AuthRequest;

struct _MahoPolkitListener {
    PolkitAgentListener parent_instance;
    GtkApplication *app;
    gpointer registration_handle;
    AuthRequest *active;
    guint64 next_request_id;
    GtkWindow *window;
    GtkLabel *action_label;
    GtkLabel *message_label;
    GtkLabel *requester_label;
    GtkLabel *identity_label;
    GtkLabel *prompt_label;
    GtkLabel *info_label;
    GtkLabel *error_label;
    GtkDropDown *identity_dropdown;
    GtkEntry *entry;
    GtkButton *cancel_button;
    GtkButton *auth_button;
    GDBusConnection *system_bus;
    guint authority_watch;
    guint lock_watch;
    gboolean authority_available;
    gboolean shutting_down;
};

struct _MahoPolkitListenerClass {
    PolkitAgentListenerClass parent_class;
};

G_DEFINE_TYPE(MahoPolkitListener, maho_polkit_listener, POLKIT_AGENT_TYPE_LISTENER)

typedef struct {
    GtkApplication *app;
    MahoPolkitListener *listener;
    gint exit_status;
    gint singleton_fd;
} AppState;

static gchar *clean_text(const gchar *value, const gchar *fallback) {
    const gchar *source = value != NULL ? value : "";
    gchar *copy = g_strndup(source, MAHO_MAX_TEXT);
    g_strstrip(copy);
    for (gchar *p = copy; *p != '\0'; ++p) {
        if (*p == '\n' || *p == '\r' || *p == '\t') {
            *p = ' ';
        }
    }
    if (*copy == '\0') {
        g_free(copy);
        return g_strdup(fallback != NULL ? fallback : "");
    }
    return copy;
}

static gchar *basename_copy(const gchar *path) {
    if (path == NULL || *path == '\0') {
        return g_strdup("");
    }
    gchar *base = g_path_get_basename(path);
    gchar *clean = clean_text(base, "");
    g_free(base);
    return clean;
}

static gboolean response_gate_consume(ResponseGate *gate, guint64 request_id, guint64 serial) {
    if (gate == NULL || gate->request_id != request_id || !gate->awaiting) {
        return FALSE;
    }
    if (serial != gate->prompt_serial || gate->responded_serial == serial) {
        return FALSE;
    }
    gate->awaiting = FALSE;
    gate->responded_serial = serial;
    return TRUE;
}

static guint64 response_gate_open(ResponseGate *gate) {
    gate->prompt_serial++;
    gate->awaiting = TRUE;
    return gate->prompt_serial;
}

static gboolean process_alive(gint pid) {
    if (pid <= 1 || kill(pid, 0) == 0) {
        return TRUE;
    }
    return errno != ESRCH;
}

static gboolean maho_lock_active(void) {
    const gchar *runtime = g_get_user_runtime_dir();
    if (runtime == NULL || *runtime == '\0') {
        return FALSE;
    }
    g_autofree gchar *path = g_build_filename(runtime, "maho-lock.lock", NULL);
    gint fd = open(path, O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        return FALSE;
    }
    gboolean active = FALSE;
    if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
        active = errno == EWOULDBLOCK || errno == EAGAIN;
    } else {
        (void)flock(fd, LOCK_UN);
    }
    close(fd);
    return active;
}

static void identity_choice_free(gpointer data) {
    IdentityChoice *choice = data;
    if (choice == NULL) {
        return;
    }
    g_clear_object(&choice->identity);
    g_free(choice->key);
    g_free(choice->label);
    g_free(choice);
}

static gchar *identity_label(PolkitIdentity *identity, gint *uid_out, gboolean *has_uid_out) {
    *uid_out = -1;
    *has_uid_out = FALSE;
    if (POLKIT_IS_UNIX_USER(identity)) {
        gint uid = polkit_unix_user_get_uid(POLKIT_UNIX_USER(identity));
        struct passwd pwd;
        struct passwd *result = NULL;
        gchar buffer[4096];
        *uid_out = uid;
        *has_uid_out = TRUE;
        if (getpwuid_r((uid_t)uid, &pwd, buffer, sizeof(buffer), &result) == 0 && result != NULL) {
            const gchar *name = pwd.pw_name != NULL ? pwd.pw_name : "user";
            const gchar *gecos = pwd.pw_gecos != NULL ? pwd.pw_gecos : "";
            const gchar *comma = strchr(gecos, ',');
            gsize length = comma != NULL ? (gsize)(comma - gecos) : strlen(gecos);
            if (length > 0 && !(strlen(name) == length && strncmp(gecos, name, length) == 0)) {
                return g_strdup_printf("%.*s (%s)", (int)length, gecos, name);
            }
            return g_strdup(name);
        }
    }
    return polkit_identity_to_string(identity);
}

static gint identity_choice_compare(gconstpointer a, gconstpointer b) {
    const IdentityChoice *left = *(IdentityChoice * const *)a;
    const IdentityChoice *right = *(IdentityChoice * const *)b;
    gint by_label = g_ascii_strcasecmp(left->label, right->label);
    return by_label != 0 ? by_label : g_strcmp0(left->key, right->key);
}

static GPtrArray *copy_identity_choices(GList *identities) {
    GPtrArray *choices = g_ptr_array_new_with_free_func(identity_choice_free);
    for (GList *node = identities; node != NULL; node = node->next) {
        PolkitIdentity *identity = POLKIT_IDENTITY(node->data);
        if (!POLKIT_IS_IDENTITY(identity)) {
            continue;
        }
        IdentityChoice *choice = g_new0(IdentityChoice, 1);
        choice->identity = g_object_ref(identity);
        choice->key = polkit_identity_to_string(identity);
        choice->label = identity_label(identity, &choice->uid, &choice->has_uid);
        if (choice->key == NULL || choice->label == NULL) {
            identity_choice_free(choice);
            continue;
        }
        g_ptr_array_add(choices, choice);
    }
    g_ptr_array_sort(choices, identity_choice_compare);
    return choices;
}

static guint default_identity_index_for_uid(GPtrArray *choices, uid_t current) {
    if (current != 0) {
        for (guint i = 0; i < choices->len; ++i) {
            IdentityChoice *choice = g_ptr_array_index(choices, i);
            if (choice->has_uid && choice->uid == (gint)current) {
                return i;
            }
        }
    }
    for (guint i = 0; i < choices->len; ++i) {
        IdentityChoice *choice = g_ptr_array_index(choices, i);
        if (!choice->has_uid || choice->uid != 0) {
            return i;
        }
    }
    return 0;
}

static guint default_identity_index(GPtrArray *choices) {
    return default_identity_index_for_uid(choices, getuid());
}

static gint requester_pid_from_details(PolkitDetails *details) {
    static const gchar *keys[] = {
        "polkit.caller-pid", "caller-pid", "subject-pid", "process-id", "pid", NULL,
    };
    for (guint i = 0; keys[i] != NULL; ++i) {
        const gchar *value = polkit_details_lookup(details, keys[i]);
        if (value == NULL || *value == '\0') {
            continue;
        }
        gchar *end = NULL;
        gint64 parsed = g_ascii_strtoll(value, &end, 10);
        if (end != value && end != NULL && *end == '\0' && parsed > 1 && parsed <= G_MAXINT) {
            return (gint)parsed;
        }
    }
    return -1;
}

static gchar *requester_from_details(PolkitDetails *details, gint pid) {
    static const gchar *keys[] = {"program", "polkit.exec.path", "command_line", NULL};
    for (guint i = 0; keys[i] != NULL; ++i) {
        const gchar *value = polkit_details_lookup(details, keys[i]);
        if (value == NULL || *value == '\0') {
            continue;
        }
        if (g_strcmp0(keys[i], "command_line") == 0) {
            g_auto(GStrv) pieces = g_strsplit(value, " ", 2);
            return basename_copy(pieces[0]);
        }
        return basename_copy(value);
    }
    if (pid > 1) {
        g_autofree gchar *path = g_strdup_printf("/proc/%d/comm", pid);
        gchar *contents = NULL;
        if (g_file_get_contents(path, &contents, NULL, NULL)) {
            gchar *clean = clean_text(contents, "");
            g_free(contents);
            if (*clean != '\0') {
                return clean;
            }
            g_free(clean);
        }
        return g_strdup_printf("Process %d", pid);
    }
    return g_strdup("PolicyKit request");
}

static gchar *palette_value(const gchar *json, const gchar *key, const gchar *fallback) {
    if (json == NULL) {
        return g_strdup(fallback);
    }
    g_autofree gchar *pattern = g_strdup_printf(
        "\\\"%s\\\"[[:space:]]*:[[:space:]]*\\\"(#[0-9A-Fa-f]{6,8})\\\"",
        key
    );
    g_autoptr(GRegex) regex = g_regex_new(pattern, 0, 0, NULL);
    GMatchInfo *match = NULL;
    if (regex != NULL && g_regex_match(regex, json, 0, &match)) {
        gchar *value = g_match_info_fetch(match, 1);
        g_match_info_free(match);
        return value;
    }
    if (match != NULL) {
        g_match_info_free(match);
    }
    return g_strdup(fallback);
}

static void apply_palette(MahoPolkitListener *self) {
    const gchar *cache = g_get_user_cache_dir();
    g_autofree gchar *path = g_build_filename(cache, "maho", "theme", "active.json", NULL);
    gchar *json = NULL;
    (void)g_file_get_contents(path, &json, NULL, NULL);

    g_autofree gchar *background = palette_value(json, "background", "#141218");
    g_autofree gchar *surface = palette_value(json, "surface_container_high", "#2b2930");
    g_autofree gchar *foreground = palette_value(json, "foreground", "#e6e1e5");
    g_autofree gchar *muted = palette_value(json, "muted", "#cac4d0");
    g_autofree gchar *outline = palette_value(json, "outline", "#938f99");
    g_autofree gchar *primary = palette_value(json, "primary", "#d0bcff");
    g_autofree gchar *error = palette_value(json, "error", "#f2b8b5");

    g_autofree gchar *css = g_strdup_printf(
        "window { background: %s; color: %s; }"
        ".maho-title { color: %s; font-size: 18px; font-weight: 700; }"
        ".maho-message { color: %s; font-size: 13px; }"
        ".maho-muted,.maho-meta { color: %s; font-size: 11px; }"
        ".maho-error { color: %s; font-size: 11px; }"
        ".maho-shield { color: %s; font-size: 28px; min-width: 48px; }"
        ".maho-card { background: %s; border-radius: 14px; padding: 10px 12px;"
        " border: 1px solid %s; }"
        "entry,dropdown { background: %s; color: %s; border-radius: 12px; padding: 10px; }"
        "button { border-radius: 12px; padding: 8px 16px; }"
        "button.suggested-action { background: %s; color: %s; }",
        background, foreground, foreground, foreground, muted, error, primary,
        surface, outline, surface, foreground, primary, background
    );
    g_free(json);

    GtkCssProvider *provider = gtk_css_provider_new();
    gtk_css_provider_load_from_string(provider, css);
    GdkDisplay *display = gtk_widget_get_display(GTK_WIDGET(self->window));
    gtk_style_context_add_provider_for_display(
        display, GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION
    );
    g_object_unref(provider);
}

static void auth_request_free(AuthRequest *request);
static void request_cancel(AuthRequest *request, const gchar *reason);
static void request_start_session(AuthRequest *request);
static void request_update_ui(AuthRequest *request);

static gboolean request_is_current(AuthRequest *request) {
    return request != NULL
        && !request->finished
        && request->owner != NULL
        && request->owner->active == request;
}

static void clear_entry_secret(MahoPolkitListener *self) {
    gtk_editable_set_text(GTK_EDITABLE(self->entry), "");
}

static void request_cleanup_session(AuthRequest *request) {
    if (request->session == NULL) {
        return;
    }
    g_signal_handlers_disconnect_by_data(request->session, request);
    g_clear_object(&request->session);
}

static void request_remove_timers(AuthRequest *request) {
    if (request->requester_watch != 0) {
        g_source_remove(request->requester_watch);
        request->requester_watch = 0;
    }
    if (request->cancel_force_watch != 0) {
        g_source_remove(request->cancel_force_watch);
        request->cancel_force_watch = 0;
    }
}

static void request_disconnect_cancellable(AuthRequest *request) {
    if (request->cancellable != NULL && request->cancel_id != 0) {
        g_cancellable_disconnect(request->cancellable, request->cancel_id);
        request->cancel_id = 0;
    }
}

static GError *polkit_error_new(PolkitError code, const gchar *message) {
    return g_error_new_literal(POLKIT_ERROR, code, message);
}

static void request_finish(AuthRequest *request, gboolean handled, GError *error) {
    if (!request_is_current(request)) {
        if (error != NULL) {
            g_error_free(error);
        }
        return;
    }

    MahoPolkitListener *self = request->owner;
    request->finished = TRUE;
    request->gate.awaiting = FALSE;
    request_remove_timers(request);
    request_disconnect_cancellable(request);
    request_cleanup_session(request);
    clear_entry_secret(self);
    gtk_widget_set_visible(GTK_WIDGET(self->window), FALSE);
    self->active = NULL;

    if (error != NULL) {
        g_task_return_error(request->task, error);
    } else {
        g_task_return_boolean(request->task, handled);
    }
    auth_request_free(request);
}

static gboolean force_cancel_timeout(gpointer data) {
    AuthRequest *request = data;
    request->cancel_force_watch = 0;
    if (!request_is_current(request)) {
        return G_SOURCE_REMOVE;
    }
    request_finish(
        request,
        FALSE,
        polkit_error_new(POLKIT_ERROR_CANCELLED, "Authentication was cancelled.")
    );
    return G_SOURCE_REMOVE;
}

static void request_cancel(AuthRequest *request, const gchar *reason) {
    if (!request_is_current(request) || request->cancel_requested) {
        return;
    }

    request->cancel_requested = TRUE;
    g_free(request->error_text);
    request->error_text = clean_text(reason, "Authentication was cancelled.");
    clear_entry_secret(request->owner);

    if (request->session == NULL) {
        request_finish(
            request,
            FALSE,
            polkit_error_new(POLKIT_ERROR_CANCELLED, request->error_text)
        );
        return;
    }

    polkit_agent_session_cancel(request->session);
    request->cancel_force_watch = g_timeout_add(1000, force_cancel_timeout, request);
}

static gboolean cancel_from_cancellable_idle(gpointer data) {
    AuthRequest *request = data;
    if (request_is_current(request)) {
        request_cancel(request, "PolicyKit cancelled the authentication request.");
    }
    return G_SOURCE_REMOVE;
}

static void on_cancellable_cancelled(GCancellable *cancellable, gpointer user_data) {
    (void)cancellable;
    g_idle_add(cancel_from_cancellable_idle, user_data);
}

static gboolean requester_watch_cb(gpointer data) {
    AuthRequest *request = data;
    if (!request_is_current(request)) {
        return G_SOURCE_REMOVE;
    }
    if (process_alive(request->requester_pid)) {
        return G_SOURCE_CONTINUE;
    }
    request->requester_watch = 0;
    request_cancel(request, "The requesting process exited.");
    return G_SOURCE_REMOVE;
}

static gboolean retry_session_idle(gpointer data) {
    AuthRequest *request = data;
    if (request_is_current(request) && !request->cancel_requested) {
        request_start_session(request);
    }
    return G_SOURCE_REMOVE;
}

static void on_session_completed(
    PolkitAgentSession *session,
    gboolean gained_authorization,
    gpointer user_data
) {
    AuthRequest *request = user_data;
    if (!request_is_current(request) || session != request->session) {
        return;
    }

    request->gate.awaiting = FALSE;
    if (request->cancel_requested) {
        request_finish(
            request,
            FALSE,
            polkit_error_new(POLKIT_ERROR_CANCELLED, request->error_text)
        );
        return;
    }

    if (gained_authorization) {
        request_finish(request, TRUE, NULL);
        return;
    }

    request_cleanup_session(request);
    request->attempt++;
    g_free(request->error_text);
    request->error_text = g_strdup("Authentication failed. Try again.");
    request_update_ui(request);
    g_idle_add(retry_session_idle, request);
}

static void on_session_request(
    PolkitAgentSession *session,
    const gchar *prompt,
    gboolean echo_on,
    gpointer user_data
) {
    AuthRequest *request = user_data;
    if (!request_is_current(request) || session != request->session) {
        if (POLKIT_AGENT_IS_SESSION(session)) {
            polkit_agent_session_cancel(session);
        }
        return;
    }

    g_free(request->prompt);
    request->prompt = clean_text(prompt, "Authentication response");
    request->echo_on = echo_on;
    (void)response_gate_open(&request->gate);
    request_update_ui(request);
}

static void on_session_info(
    PolkitAgentSession *session,
    const gchar *text,
    gpointer user_data
) {
    AuthRequest *request = user_data;
    if (!request_is_current(request) || session != request->session) {
        return;
    }
    g_free(request->info_text);
    request->info_text = clean_text(text, "");
    request_update_ui(request);
}

static void on_session_error(
    PolkitAgentSession *session,
    const gchar *text,
    gpointer user_data
) {
    AuthRequest *request = user_data;
    if (!request_is_current(request) || session != request->session) {
        return;
    }
    g_free(request->error_text);
    request->error_text = clean_text(text, "Authentication failed.");
    request_update_ui(request);
}

static void request_start_session(AuthRequest *request) {
    if (!request_is_current(request) || request->session != NULL || request->identities->len == 0) {
        return;
    }
    if (request->selected_index >= request->identities->len) {
        request_cancel(request, "The selected authentication identity is no longer valid.");
        return;
    }

    IdentityChoice *choice = g_ptr_array_index(request->identities, request->selected_index);
    request->session = polkit_agent_session_new(choice->identity, request->cookie);
    if (request->session == NULL) {
        request_finish(
            request,
            FALSE,
            polkit_error_new(POLKIT_ERROR_FAILED, "PolicyKit could not create an authentication session.")
        );
        return;
    }

    g_signal_connect(request->session, "completed", G_CALLBACK(on_session_completed), request);
    g_signal_connect(request->session, "request", G_CALLBACK(on_session_request), request);
    g_signal_connect(request->session, "show-info", G_CALLBACK(on_session_info), request);
    g_signal_connect(request->session, "show-error", G_CALLBACK(on_session_error), request);

    gtk_widget_set_sensitive(GTK_WIDGET(request->owner->identity_dropdown), FALSE);
    gtk_widget_set_sensitive(GTK_WIDGET(request->owner->entry), FALSE);
    gtk_button_set_label(request->owner->auth_button, "Waiting…");
    gtk_widget_set_sensitive(GTK_WIDGET(request->owner->auth_button), FALSE);
    polkit_agent_session_initiate(request->session);
}

static void request_update_ui(AuthRequest *request) {
    if (!request_is_current(request)) {
        return;
    }

    MahoPolkitListener *self = request->owner;
    IdentityChoice *choice = g_ptr_array_index(request->identities, request->selected_index);
    g_autofree gchar *identity = g_strdup_printf("Authenticate as: %s", choice->label);
    gtk_label_set_text(self->identity_label, identity);
    gtk_label_set_text(self->prompt_label, request->prompt != NULL ? request->prompt : "Password");
    gtk_label_set_text(self->info_label, request->info_text != NULL ? request->info_text : "");
    gtk_label_set_text(self->error_label, request->error_text != NULL ? request->error_text : "");

    gboolean session_started = request->session != NULL;
    gboolean ready_for_response = session_started && request->gate.awaiting;
    gboolean choosing_identity = !session_started && request->identities->len > 1;

    gtk_widget_set_visible(GTK_WIDGET(self->entry), !choosing_identity);
    gtk_widget_set_sensitive(GTK_WIDGET(self->entry), ready_for_response);
    gtk_entry_set_visibility(self->entry, ready_for_response ? request->echo_on : FALSE);
    gtk_widget_set_sensitive(
        GTK_WIDGET(self->identity_dropdown),
        !session_started && request->identities->len > 1
    );

    if (choosing_identity) {
        gtk_button_set_label(self->auth_button, "Continue");
        gtk_widget_set_sensitive(GTK_WIDGET(self->auth_button), TRUE);
    } else if (ready_for_response) {
        gtk_button_set_label(self->auth_button, request->attempt > 0 ? "Try Again" : "Authenticate");
        gtk_widget_set_sensitive(GTK_WIDGET(self->auth_button), TRUE);
        gtk_widget_grab_focus(GTK_WIDGET(self->entry));
    } else {
        gtk_button_set_label(self->auth_button, "Waiting…");
        gtk_widget_set_sensitive(GTK_WIDGET(self->auth_button), FALSE);
    }
}

static void on_identity_changed(GObject *object, GParamSpec *pspec, gpointer user_data) {
    (void)pspec;
    MahoPolkitListener *self = user_data;
    AuthRequest *request = self->active;
    if (!request_is_current(request) || request->session != NULL) {
        return;
    }

    guint selected = gtk_drop_down_get_selected(GTK_DROP_DOWN(object));
    if (selected >= request->identities->len) {
        return;
    }
    request->selected_index = selected;
    request_update_ui(request);
}

static void submit_current(MahoPolkitListener *self) {
    AuthRequest *request = self->active;
    if (!request_is_current(request)) {
        return;
    }

    if (request->session == NULL) {
        request_start_session(request);
        return;
    }

    guint64 serial = request->gate.prompt_serial;
    if (!response_gate_consume(&request->gate, request->gate.request_id, serial)) {
        return;
    }

    const gchar *text = gtk_editable_get_text(GTK_EDITABLE(self->entry));
    gchar *response = g_strdup(text != NULL ? text : "");
    clear_entry_secret(self);
    gtk_widget_set_sensitive(GTK_WIDGET(self->entry), FALSE);
    gtk_widget_set_sensitive(GTK_WIDGET(self->auth_button), FALSE);
    gtk_button_set_label(self->auth_button, "Waiting…");

    polkit_agent_session_response(request->session, response);
    if (response != NULL) {
        explicit_bzero(response, strlen(response));
        g_free(response);
    }
}

static void on_auth_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    submit_current(MAHO_POLKIT_LISTENER(user_data));
}

static void on_cancel_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    MahoPolkitListener *self = MAHO_POLKIT_LISTENER(user_data);
    if (self->active != NULL) {
        request_cancel(self->active, "Authentication was cancelled.");
    }
}

static gboolean on_window_close(GtkWindow *window, gpointer user_data) {
    (void)window;
    MahoPolkitListener *self = MAHO_POLKIT_LISTENER(user_data);
    if (self->active != NULL) {
        request_cancel(self->active, "Authentication was cancelled.");
    }
    return TRUE;
}

static gboolean on_key_pressed(
    GtkEventControllerKey *controller,
    guint keyval,
    guint keycode,
    GdkModifierType state,
    gpointer user_data
) {
    (void)controller;
    (void)keycode;
    (void)state;

    if (keyval == GDK_KEY_Escape) {
        MahoPolkitListener *self = MAHO_POLKIT_LISTENER(user_data);
        if (self->active != NULL) {
            request_cancel(self->active, "Authentication was cancelled.");
        }
        return TRUE;
    }
    return FALSE;
}

static void build_window(MahoPolkitListener *self) {
    self->window = GTK_WINDOW(gtk_application_window_new(self->app));
    gtk_window_set_title(self->window, "Authentication Required");
    gtk_window_set_default_size(self->window, 430, -1);
    gtk_window_set_resizable(self->window, FALSE);
    gtk_window_set_modal(self->window, TRUE);
    gtk_window_set_hide_on_close(self->window, TRUE);
    g_signal_connect(self->window, "close-request", G_CALLBACK(on_window_close), self);

    GtkEventController *key = gtk_event_controller_key_new();
    g_signal_connect(key, "key-pressed", G_CALLBACK(on_key_pressed), self);
    gtk_widget_add_controller(GTK_WIDGET(self->window), key);

    GtkWidget *outer = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_widget_set_margin_top(outer, 22);
    gtk_widget_set_margin_bottom(outer, 20);
    gtk_widget_set_margin_start(outer, 22);
    gtk_widget_set_margin_end(outer, 22);
    gtk_window_set_child(self->window, outer);

    GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    GtkWidget *shield = gtk_label_new("󰌆");
    gtk_widget_add_css_class(shield, "maho-shield");
    gtk_box_append(GTK_BOX(header), shield);

    GtkWidget *titles = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
    GtkWidget *title = gtk_label_new("Authentication Required");
    gtk_label_set_xalign(GTK_LABEL(title), 0.0f);
    gtk_widget_add_css_class(title, "maho-title");
    gtk_box_append(GTK_BOX(titles), title);

    self->action_label = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(self->action_label, 0.0f);
    gtk_widget_add_css_class(GTK_WIDGET(self->action_label), "maho-muted");
    gtk_box_append(GTK_BOX(titles), GTK_WIDGET(self->action_label));
    gtk_box_append(GTK_BOX(header), titles);
    gtk_box_append(GTK_BOX(outer), header);

    self->message_label = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(self->message_label, 0.0f);
    gtk_label_set_wrap(self->message_label, TRUE);
    gtk_widget_add_css_class(GTK_WIDGET(self->message_label), "maho-message");
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->message_label));

    GtkWidget *meta = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
    gtk_widget_add_css_class(meta, "maho-card");
    self->requester_label = GTK_LABEL(gtk_label_new(""));
    self->identity_label = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(self->requester_label, 0.0f);
    gtk_label_set_xalign(self->identity_label, 0.0f);
    gtk_widget_add_css_class(GTK_WIDGET(self->requester_label), "maho-meta");
    gtk_widget_add_css_class(GTK_WIDGET(self->identity_label), "maho-meta");
    gtk_box_append(GTK_BOX(meta), GTK_WIDGET(self->requester_label));
    gtk_box_append(GTK_BOX(meta), GTK_WIDGET(self->identity_label));
    gtk_box_append(GTK_BOX(outer), meta);

    self->identity_dropdown = GTK_DROP_DOWN(gtk_drop_down_new(NULL, NULL));
    g_signal_connect(
        self->identity_dropdown,
        "notify::selected",
        G_CALLBACK(on_identity_changed),
        self
    );
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->identity_dropdown));

    self->prompt_label = GTK_LABEL(gtk_label_new("Password"));
    gtk_label_set_xalign(self->prompt_label, 0.0f);
    gtk_widget_add_css_class(GTK_WIDGET(self->prompt_label), "maho-muted");
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->prompt_label));

    self->entry = GTK_ENTRY(gtk_entry_new());
    gtk_entry_set_visibility(self->entry, FALSE);
    gtk_entry_set_input_purpose(self->entry, GTK_INPUT_PURPOSE_PASSWORD);
    gtk_entry_set_activates_default(self->entry, TRUE);
    g_signal_connect_swapped(self->entry, "activate", G_CALLBACK(submit_current), self);
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->entry));

    self->info_label = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(self->info_label, 0.0f);
    gtk_label_set_wrap(self->info_label, TRUE);
    gtk_widget_add_css_class(GTK_WIDGET(self->info_label), "maho-muted");
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->info_label));

    self->error_label = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(self->error_label, 0.0f);
    gtk_label_set_wrap(self->error_label, TRUE);
    gtk_widget_add_css_class(GTK_WIDGET(self->error_label), "maho-error");
    gtk_box_append(GTK_BOX(outer), GTK_WIDGET(self->error_label));

    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    gtk_widget_set_halign(actions, GTK_ALIGN_END);

    self->cancel_button = GTK_BUTTON(gtk_button_new_with_label("Cancel"));
    g_signal_connect(self->cancel_button, "clicked", G_CALLBACK(on_cancel_clicked), self);
    gtk_box_append(GTK_BOX(actions), GTK_WIDGET(self->cancel_button));

    self->auth_button = GTK_BUTTON(gtk_button_new_with_label("Authenticate"));
    gtk_widget_add_css_class(GTK_WIDGET(self->auth_button), "suggested-action");
    g_signal_connect(self->auth_button, "clicked", G_CALLBACK(on_auth_clicked), self);
    gtk_box_append(GTK_BOX(actions), GTK_WIDGET(self->auth_button));
    gtk_box_append(GTK_BOX(outer), actions);

    gtk_window_set_default_widget(self->window, GTK_WIDGET(self->auth_button));
    apply_palette(self);
}

static void present_request(AuthRequest *request) {
    MahoPolkitListener *self = request->owner;
    apply_palette(self);
    clear_entry_secret(self);
    gtk_label_set_text(self->action_label, request->action_id);
    gtk_label_set_text(self->message_label, request->message);

    g_autofree gchar *requester = request->requester_pid > 1
        ? g_strdup_printf("Requested by: %s · PID %d", request->requester, request->requester_pid)
        : g_strdup_printf("Requested by: %s", request->requester);
    gtk_label_set_text(self->requester_label, requester);

    GtkStringList *model = gtk_string_list_new(NULL);
    for (guint i = 0; i < request->identities->len; ++i) {
        IdentityChoice *choice = g_ptr_array_index(request->identities, i);
        gtk_string_list_append(model, choice->label);
    }
    gtk_drop_down_set_model(self->identity_dropdown, G_LIST_MODEL(model));
    g_object_unref(model);

    gtk_drop_down_set_selected(self->identity_dropdown, request->selected_index);
    gtk_widget_set_visible(GTK_WIDGET(self->identity_dropdown), request->identities->len > 1);

    request_update_ui(request);
    gtk_window_present(self->window);

    if (request->identities->len == 1) {
        request_start_session(request);
    }
}

static void auth_request_free(AuthRequest *request) {
    if (request == NULL) {
        return;
    }
    request_remove_timers(request);
    request_disconnect_cancellable(request);
    request_cleanup_session(request);
    g_clear_object(&request->cancellable);
    g_clear_object(&request->task);
    g_clear_pointer(&request->identities, g_ptr_array_unref);
    g_free(request->action_id);
    g_free(request->message);
    g_free(request->cookie);
    g_free(request->requester);
    g_free(request->prompt);
    g_free(request->info_text);
    g_free(request->error_text);
    g_free(request);
}

static void listener_initiate_authentication(
    PolkitAgentListener *listener,
    const gchar *action_id,
    const gchar *message,
    const gchar *icon_name,
    PolkitDetails *details,
    const gchar *cookie,
    GList *identities,
    GCancellable *cancellable,
    GAsyncReadyCallback callback,
    gpointer user_data
) {
    (void)icon_name;
    MahoPolkitListener *self = MAHO_POLKIT_LISTENER(listener);
    GTask *task = g_task_new(listener, cancellable, callback, user_data);

    if (self->shutting_down || !self->authority_available) {
        g_task_return_new_error(
            task, POLKIT_ERROR, POLKIT_ERROR_FAILED, "PolicyKit authority is unavailable."
        );
        g_object_unref(task);
        return;
    }

    g_autofree gchar *clean_action = clean_text(action_id, "");
    g_autofree gchar *clean_message = clean_text(message, "");
    g_autofree gchar *clean_cookie = clean_text(cookie, "");

    if (*clean_action == '\0' || *clean_message == '\0' || *clean_cookie == '\0' || identities == NULL) {
        g_task_return_new_error(
            task, POLKIT_ERROR, POLKIT_ERROR_FAILED, "Malformed authentication request."
        );
        g_object_unref(task);
        return;
    }

    if (self->active != NULL) {
        g_task_return_new_error(
            task, POLKIT_ERROR, POLKIT_ERROR_FAILED,
            "Another authentication request is already active."
        );
        g_object_unref(task);
        return;
    }

    if (maho_lock_active()) {
        g_task_return_new_error(
            task, POLKIT_ERROR, POLKIT_ERROR_CANCELLED,
            "Authentication is unavailable while the session is locked."
        );
        g_object_unref(task);
        return;
    }

    GPtrArray *choices = copy_identity_choices(identities);
    if (choices->len == 0) {
        g_ptr_array_unref(choices);
        g_task_return_new_error(
            task, POLKIT_ERROR, POLKIT_ERROR_FAILED,
            "PolicyKit did not provide a valid authentication identity."
        );
        g_object_unref(task);
        return;
    }

    AuthRequest *request = g_new0(AuthRequest, 1);
    request->owner = self;
    request->task = task;
    request->cancellable = cancellable != NULL ? g_object_ref(cancellable) : NULL;
    request->identities = choices;
    request->action_id = g_strdup(clean_action);
    request->message = g_strdup(clean_message);
    request->cookie = g_strdup(clean_cookie);
    request->requester_pid = requester_pid_from_details(details);
    request->requester = requester_from_details(details, request->requester_pid);
    request->prompt = g_strdup("Password");
    request->info_text = g_strdup("");
    request->error_text = g_strdup("");
    request->selected_index = default_identity_index(choices);
    request->gate.request_id = self->next_request_id++;
    self->active = request;

    if (request->cancellable != NULL) {
        if (g_cancellable_is_cancelled(request->cancellable)) {
            request_cancel(request, "PolicyKit cancelled the authentication request.");
            return;
        }
        request->cancel_id = g_cancellable_connect(
            request->cancellable,
            G_CALLBACK(on_cancellable_cancelled),
            request,
            NULL
        );
        if (self->active != request) {
            return;
        }
    }

    if (request->requester_pid > 1) {
        request->requester_watch = g_timeout_add(500, requester_watch_cb, request);
    }
    present_request(request);
}

static gboolean listener_initiate_authentication_finish(
    PolkitAgentListener *listener,
    GAsyncResult *result,
    GError **error
) {
    g_return_val_if_fail(g_task_is_valid(result, listener), FALSE);
    return g_task_propagate_boolean(G_TASK(result), error);
}

static void maho_polkit_listener_dispose(GObject *object) {
    MahoPolkitListener *self = MAHO_POLKIT_LISTENER(object);
    self->shutting_down = TRUE;

    if (self->active != NULL) {
        AuthRequest *request = self->active;
        if (request->session != NULL) {
            polkit_agent_session_cancel(request->session);
        }
        request_finish(
            request,
            FALSE,
            polkit_error_new(POLKIT_ERROR_CANCELLED, "Authentication agent stopped.")
        );
    }

    if (self->lock_watch != 0) {
        g_source_remove(self->lock_watch);
        self->lock_watch = 0;
    }
    if (self->system_bus != NULL && self->authority_watch != 0) {
        g_dbus_connection_signal_unsubscribe(self->system_bus, self->authority_watch);
        self->authority_watch = 0;
    }
    g_clear_object(&self->system_bus);

    if (self->registration_handle != NULL) {
        polkit_agent_listener_unregister(self->registration_handle);
        self->registration_handle = NULL;
    }

    G_OBJECT_CLASS(maho_polkit_listener_parent_class)->dispose(object);
}

static void maho_polkit_listener_class_init(MahoPolkitListenerClass *klass) {
    GObjectClass *object_class = G_OBJECT_CLASS(klass);
    object_class->dispose = maho_polkit_listener_dispose;

    PolkitAgentListenerClass *listener_class = POLKIT_AGENT_LISTENER_CLASS(klass);
    listener_class->initiate_authentication = listener_initiate_authentication;
    listener_class->initiate_authentication_finish = listener_initiate_authentication_finish;
}

static void maho_polkit_listener_init(MahoPolkitListener *self) {
    self->next_request_id = 1;
    self->authority_available = TRUE;
}

static gboolean lock_watch_cb(gpointer data) {
    MahoPolkitListener *self = data;
    if (self->shutting_down) {
        return G_SOURCE_REMOVE;
    }
    if (self->active != NULL && maho_lock_active()) {
        request_cancel(
            self->active,
            "Authentication was cancelled because the session locked."
        );
    }
    return G_SOURCE_CONTINUE;
}

static void on_authority_owner_changed(
    GDBusConnection *connection,
    const gchar *sender_name,
    const gchar *object_path,
    const gchar *interface_name,
    const gchar *signal_name,
    GVariant *parameters,
    gpointer user_data
) {
    (void)connection;
    (void)sender_name;
    (void)object_path;
    (void)interface_name;
    (void)signal_name;

    MahoPolkitListener *self = user_data;
    const gchar *name = NULL;
    const gchar *old_owner = NULL;
    const gchar *new_owner = NULL;
    g_variant_get(parameters, "(&s&s&s)", &name, &old_owner, &new_owner);

    if (g_strcmp0(name, MAHO_POLKIT_BUS_NAME) == 0 && *old_owner != '\0' && *new_owner == '\0') {
        self->authority_available = FALSE;
        if (self->active != NULL) {
            request_cancel(self->active, "PolicyKit authority became unavailable.");
        }
        self->shutting_down = TRUE;
        g_application_quit(G_APPLICATION(self->app));
    }
}

static gboolean listener_register(MahoPolkitListener *self, GError **error) {
    g_return_val_if_fail(self->registration_handle == NULL, FALSE);

    PolkitSubject *subject = polkit_unix_session_new_for_process_sync(getpid(), NULL, error);
    if (subject == NULL) {
        return FALSE;
    }

    self->registration_handle = polkit_agent_listener_register(
        POLKIT_AGENT_LISTENER(self),
        POLKIT_AGENT_REGISTER_FLAGS_NONE,
        subject,
        MAHO_AGENT_OBJECT_PATH,
        NULL,
        error
    );
    g_object_unref(subject);

    if (self->registration_handle == NULL) {
        return FALSE;
    }

    self->system_bus = g_bus_get_sync(G_BUS_TYPE_SYSTEM, NULL, error);
    if (self->system_bus == NULL) {
        polkit_agent_listener_unregister(self->registration_handle);
        self->registration_handle = NULL;
        return FALSE;
    }

    self->authority_watch = g_dbus_connection_signal_subscribe(
        self->system_bus,
        "org.freedesktop.DBus",
        "org.freedesktop.DBus",
        "NameOwnerChanged",
        "/org/freedesktop/DBus",
        MAHO_POLKIT_BUS_NAME,
        G_DBUS_SIGNAL_FLAGS_NONE,
        on_authority_owner_changed,
        self,
        NULL
    );
    self->lock_watch = g_timeout_add(250, lock_watch_cb, self);
    return TRUE;
}

static gint acquire_singleton_lock(void) {
    const gchar *runtime = g_get_user_runtime_dir();
    if (runtime == NULL || *runtime == '\0') {
        return -1;
    }

    g_autofree gchar *dir = g_build_filename(runtime, "maho", NULL);
    if (g_mkdir_with_parents(dir, 0700) != 0) {
        return -1;
    }
    (void)chmod(dir, 0700);

    g_autofree gchar *path = g_build_filename(dir, "polkit-agent.lock", NULL);
    gint fd = open(path, O_CREAT | O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) {
        return -1;
    }
    (void)fchmod(fd, 0600);

    if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
        close(fd);
        return -2;
    }
    return fd;
}

static gboolean quit_from_signal(gpointer data) {
    AppState *state = data;
    g_application_quit(G_APPLICATION(state->app));
    return G_SOURCE_REMOVE;
}

static void on_activate(GtkApplication *app, gpointer user_data) {
    AppState *state = user_data;
    if (state->listener != NULL) {
        return;
    }

    if (gdk_display_get_default() == NULL) {
        g_printerr("maho-polkit-agent: graphical display is unavailable\n");
        state->exit_status = 1;
        g_application_quit(G_APPLICATION(app));
        return;
    }

    MahoPolkitListener *listener = g_object_new(MAHO_TYPE_POLKIT_LISTENER, NULL);
    listener->app = app;
    build_window(listener);

    g_autoptr(GError) error = NULL;
    if (!listener_register(listener, &error)) {
        g_printerr(
            "maho-polkit-agent: PolicyKit registration failed: %s\n",
            error != NULL ? error->message : "unknown error"
        );
        state->exit_status = 1;
        g_object_unref(listener);
        g_application_quit(G_APPLICATION(app));
        return;
    }

    state->listener = listener;
    g_application_hold(G_APPLICATION(app));
}

static void on_shutdown(GApplication *application, gpointer user_data) {
    (void)application;
    AppState *state = user_data;

    if (state->listener != NULL) {
        state->listener->shutting_down = TRUE;
        g_clear_object(&state->listener);
    }
    if (state->singleton_fd >= 0) {
        (void)flock(state->singleton_fd, LOCK_UN);
        close(state->singleton_fd);
        state->singleton_fd = -1;
    }
}

static gboolean self_test_expect(gboolean condition, const gchar *name) {
    if (!condition) {
        g_printerr("FAIL  %s\n", name);
        return FALSE;
    }
    g_print("PASS  %s\n", name);
    return TRUE;
}

static int run_self_tests(void) {
    gboolean ok = TRUE;

    ResponseGate gate = {.request_id = 9};
    guint64 first = response_gate_open(&gate);
    ok &= self_test_expect(response_gate_consume(&gate, 9, first), "first response accepted");
    ok &= self_test_expect(!response_gate_consume(&gate, 9, first), "duplicate response rejected");
    guint64 second = response_gate_open(&gate);
    ok &= self_test_expect(!response_gate_consume(&gate, 8, second), "stale request rejected");
    ok &= self_test_expect(!response_gate_consume(&gate, 9, first), "stale prompt rejected");
    ok &= self_test_expect(response_gate_consume(&gate, 9, second), "current prompt accepted");

    GPtrArray *choices = g_ptr_array_new_with_free_func(identity_choice_free);
    IdentityChoice *root = g_new0(IdentityChoice, 1);
    root->label = g_strdup("root");
    root->key = g_strdup("unix-user:0");
    root->has_uid = TRUE;
    root->uid = 0;
    g_ptr_array_add(choices, root);

    IdentityChoice *user = g_new0(IdentityChoice, 1);
    user->label = g_strdup("user");
    user->key = g_strdup("unix-user:1000");
    user->has_uid = TRUE;
    user->uid = 1000;
    g_ptr_array_add(choices, user);

    ok &= self_test_expect(
        default_identity_index_for_uid(choices, 1000) == 1,
        "current identity preferred"
    );
    ok &= self_test_expect(
        default_identity_index_for_uid(choices, 2000) == 1,
        "root is not silently preferred"
    );
    ok &= self_test_expect(
        default_identity_index_for_uid(choices, 0) == 1,
        "root session still prefers non-root identity"
    );
    g_ptr_array_unref(choices);

    PolkitDetails *details = polkit_details_new();
    polkit_details_insert(details, "program", "/usr/bin/maho-test-client");
    polkit_details_insert(details, "caller-pid", "4242");
    ok &= self_test_expect(
        requester_pid_from_details(details) == 4242,
        "request pid parsed"
    );
    gchar *requester = requester_from_details(details, 4242);
    ok &= self_test_expect(
        g_strcmp0(requester, "maho-test-client") == 0,
        "request application sanitized"
    );
    g_free(requester);
    g_object_unref(details);

    gchar *clean = clean_text(" hello\nworld\t", "");
    ok &= self_test_expect(
        g_strcmp0(clean, "hello world") == 0,
        "human text sanitized"
    );
    g_free(clean);

    ok &= self_test_expect(process_alive(getpid()), "live requester accepted");
    ok &= self_test_expect(!process_alive(G_MAXINT), "dead requester rejected");

    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc == 2 && g_strcmp0(argv[1], "--self-test") == 0) {
        return run_self_tests();
    }
    if (argc > 2 || (argc == 2 && g_strcmp0(argv[1], "run") != 0)) {
        g_printerr("usage: maho-polkit-agent [run|--self-test]\n");
        return 2;
    }

    AppState state = {
        .app = NULL,
        .listener = NULL,
        .exit_status = 0,
        .singleton_fd = -1,
    };

    state.singleton_fd = acquire_singleton_lock();
    if (state.singleton_fd == -2) {
        g_printerr("maho-polkit-agent: another instance is already running\n");
        return 0;
    }
    if (state.singleton_fd < 0) {
        g_printerr("maho-polkit-agent: could not acquire session singleton lock\n");
        return 1;
    }

    state.app = gtk_application_new(
        "io.maho.PolkitAgent",
        G_APPLICATION_DEFAULT_FLAGS
    );
    g_signal_connect(state.app, "activate", G_CALLBACK(on_activate), &state);
    g_signal_connect(state.app, "shutdown", G_CALLBACK(on_shutdown), &state);

    g_unix_signal_add(SIGTERM, quit_from_signal, &state);
    g_unix_signal_add(SIGINT, quit_from_signal, &state);

    int app_argc = argc == 2 ? 1 : argc;
    int result = g_application_run(G_APPLICATION(state.app), app_argc, argv);
    g_object_unref(state.app);
    return state.exit_status != 0 ? state.exit_status : result;
}
