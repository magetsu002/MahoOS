#include <gio/gio.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
static GDBusConnection *connect_bus(void) {
 GError *e=NULL; char *address=g_dbus_address_get_for_bus_sync(G_BUS_TYPE_SYSTEM,NULL,&e);
 if (!address) {fprintf(stderr,"bus address: %s\n",e->message);exit(2);}
 GDBusConnection *c=g_dbus_connection_new_for_address_sync(address,G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT|G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION,NULL,NULL,&e);
 g_free(address); if (!c) {fprintf(stderr,"bus connection: %s\n",e->message);exit(2);}return c;
}
static GVariant *call(GDBusConnection *c,const char *method,const char *args,int permitted_failure) {
 GError *e=NULL; GVariant *v=g_variant_parse(NULL,args,NULL,NULL,&e);
 if (!v) {fprintf(stderr,"variant: %s\n",e->message);exit(2);}
 GVariant *r=g_dbus_connection_call_sync(c,"org.opensuse.Snapper","/org/opensuse/Snapper","org.opensuse.Snapper",method,v,NULL,G_DBUS_CALL_FLAGS_NONE,30000,NULL,&e);
 if (!r) {fprintf(stderr,"%s: %s\n",method,e->message);if (!permitted_failure)exit(2);g_error_free(e);}return r;
}
int main(void) {
 if (geteuid()!=0 || !getenv("MAHO_DISPOSABLE_VM_TEST") || strcmp(getenv("MAHO_DISPOSABLE_VM_TEST"),"1")) return 3;
 char product[128]={0}; FILE *dmi=fopen("/sys/class/dmi/id/product_name","r");
 if (!dmi || !fgets(product,sizeof product,dmi)) return 3; fclose(dmi);
 if (strncmp(product,"Standard PC",11) && strncmp(product,"QEMU",4)) return 3;
 GDBusConnection *a=connect_bus(), *b=connect_bus();
 GVariant *r=call(a,"CreateSingleSnapshot","('maho-vm-lock-probe','Maho disposable lock probe','timeline',@a{ss} {})",0);
 guint32 n=0;g_variant_get(r,"(u)",&n);g_variant_unref(r);
 call(a,"LockConfig","('maho-vm-lock-probe',)",0);
 char text[512];snprintf(text,sizeof text,"('maho-vm-lock-probe',uint32 %u,'Maho disposable promoted protection','',{'important':'yes','maho.known_good':'yes'})",n);
 r=call(b,"SetSnapshot",text,1);int promoted=(r!=NULL);if(r)g_variant_unref(r);
 snprintf(text,sizeof text,"('maho-vm-lock-probe',@au [uint32 %u])",n);
 r=call(b,"DeleteSnapshots",text,1);int other_delete_blocked=(r==NULL);if(r)g_variant_unref(r);
 snprintf(text,sizeof text,"('maho-vm-lock-probe',uint32 %u)",n);
 r=call(a,"GetSnapshot",text,0);char *observed=g_variant_print(r,TRUE);printf("snapshot_after_probe=%s\n",observed);g_free(observed);g_variant_unref(r);
 call(a,"UnlockConfig","('maho-vm-lock-probe',)",0);
 printf("{\"snapshot_number\":%u,\"metadata_promotion_allowed_under_other_client_lock\":%s,\"other_client_deletion_blocked\":%s,\"snapshot_retirement_certified\":false}\n",n,promoted?"true":"false",other_delete_blocked?"true":"false");
 g_dbus_connection_close_sync(a,NULL,NULL);g_dbus_connection_close_sync(b,NULL,NULL);
 return promoted && other_delete_blocked ? 0 : 4;
}
