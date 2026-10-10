/* Disposable-VM proof of the version-pinned Snapper owner-exclusion patch.
 * This does not issue snapshot retirement authority. */
#include <gio/gio.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#define CONFIG "maho-vm-owner-probe"
static unsigned checks = 0;
static void require(int truth, const char *name) {
 if (!truth) {fprintf(stderr,"FAIL %s\n",name);exit(5);} ++checks;printf("PASS %s\n",name);fflush(stdout);
}
static GDBusConnection *connect_bus(void) {
 GError *e=NULL;char *addr=g_dbus_address_get_for_bus_sync(G_BUS_TYPE_SYSTEM,NULL,&e);
 if(!addr){fprintf(stderr,"bus address failed\n");exit(2);}
 GDBusConnection *c=g_dbus_connection_new_for_address_sync(addr,G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT|G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION,NULL,NULL,&e);
 g_free(addr);if(!c){fprintf(stderr,"bus connection failed\n");exit(2);}return c;
}
static GVariant *call(GDBusConnection *c,const char *method,const char *args,int failure_ok) {
 GError *e=NULL;GVariant *v=g_variant_parse(NULL,args,NULL,NULL,&e);
 if(!v){fprintf(stderr,"variant error: %s\n",e->message);exit(2);}
 GVariant *r=g_dbus_connection_call_sync(c,"org.opensuse.Snapper","/org/opensuse/Snapper","org.opensuse.Snapper",method,v,NULL,G_DBUS_CALL_FLAGS_NONE,10000,NULL,&e);
 if(!r){if(!failure_ok){fprintf(stderr,"%s: %s\n",method,e->message);exit(2);}require(strstr(e->message,"locked")!=NULL,"denial comes from owner lock");g_error_free(e);}return r;
}
static void done(GVariant *v){if(v)g_variant_unref(v);}
static guint32 create(GDBusConnection *c,const char *userdata){
 char s[512];snprintf(s,sizeof s,"('%s','Maho disposable owner boundary','timeline',%s)",CONFIG,userdata);
 GVariant *v=call(c,"CreateSingleSnapshot",s,0);guint32 n;g_variant_get(v,"(u)",&n);done(v);return n;
}
static guint32 pair(GDBusConnection *c,guint32 *pre){
 GVariant *v=call(c,"CreatePreSnapshot","('" CONFIG "','Maho disposable extent pre','number',@a{ss} {})",0);
 g_variant_get(v,"(u)",pre);done(v);char text[256];
 snprintf(text,sizeof text,"('%s',uint32 %u,'Maho disposable extent post','number',@a{ss} {})",CONFIG,*pre);
 v=call(c,"CreatePostSnapshot",text,0);guint32 post;g_variant_get(v,"(u)",&post);done(v);return post;
}
static int protected(GDBusConnection *c,guint32 n){
 char s[128];snprintf(s,sizeof s,"('%s',uint32 %u)",CONFIG,n);GVariant *v=call(c,"GetSnapshot",s,0);
 GVariant *row=g_variant_get_child_value(v,0);
 require(g_variant_n_children(row)==8,"exact backend snapshot struct observed");
 GVariant *last=g_variant_get_child_value(row,7);const gchar *value=NULL;
 int pin=g_variant_lookup(last,"important","&s",&value)&&!strcmp(value,"yes");done(last);done(row);done(v);return pin;
}
static unsigned long long available(void){
 struct statvfs st;require(statvfs("/var/lib/maho-vm-owner-probe",&st)==0,"observe actual fixture filesystem availability");
 return (unsigned long long)st.f_bavail*st.f_frsize;
}
static void extent_case(void){
 GDBusConnection *a=connect_bus();done(call(a,"LockConfig","('" CONFIG "',)",0));
 GVariant *cfg=call(a,"GetConfig","('" CONFIG "',)",0);
 GVariant *row=g_variant_get_child_value(cfg,0),*values=g_variant_get_child_value(row,2);const gchar *limit=NULL;
 require(g_variant_lookup(values,"NUMBER_LIMIT","&s",&limit)&&!strcmp(limit,"20"),"unchanged exact count floor observed under owner exclusion");
 done(values);done(row);done(cfg);
 /* Fixture only: make newly created own objects old enough for its policy.
  * This does not alter production policy or weaken the count floor. */
 done(call(a,"SetConfig","('" CONFIG "',{'NUMBER_MIN_AGE':'0'})",0));
 const char *path="/var/lib/maho-vm-owner-probe/maho-owned-capacity-probe";
 int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
 require(fd>=0,"create only exact new VM fixture file");
 int random=open("/dev/urandom",O_RDONLY|O_CLOEXEC);require(random>=0,"random capacity fixture opened");
 char buf[65536];for(int i=0;i<512;i++){
   if(read(random,buf,sizeof buf)!=sizeof buf || write(fd,buf,sizeof buf)!=sizeof buf){fprintf(stderr,"capacity fixture I/O failed\n");exit(6);}
 }
 close(random);require(fsync(fd)==0,"durable own capacity fixture");close(fd);
 guint32 pre=0,post=pair(a,&pre);
 require(unlink(path)==0,"remove only own newly created fixture file");
 /* Twenty newer ordinary snapshots satisfy the unchanged NUMBER_LIMIT=20.
  * Existing important snapshots from the other tests remain untouched. */
 for(int i=0;i<20;i++)done(call(a,"CreateSingleSnapshot","('" CONFIG "','Retained count floor','number',@a{ss} {})",0));
 require(!protected(a,pre)&&!protected(a,post),"exact own pre/post pair freshly unprotected");
 const char *cli=getenv("MAHO_SNAPPER_OWNER_CLI");require(cli!=NULL,"exact VM CLI configured");

 char *before_argv[]={"/usr/bin/btrfs","filesystem","sync","/var/lib/maho-vm-owner-probe",NULL};gint status;GError *e=NULL;
 require(g_spawn_sync(NULL,before_argv,NULL,0,NULL,NULL,NULL,NULL,&status,&e)&&status==0,"sync before actual capacity measurement");
 unsigned long long before=available();
 char text[128];snprintf(text,sizeof text,"('%s',@au [uint32 %u,uint32 %u])",CONFIG,pre,post);
 done(call(a,"DeleteSnapshots",text,0));
 done(call(a,"Sync","('" CONFIG "',)",0));
 char *sync_argv[]={"/usr/bin/btrfs","subvolume","sync","/var/lib/maho-vm-owner-probe",NULL};
 require(g_spawn_sync(NULL,sync_argv,NULL,0,NULL,NULL,NULL,NULL,&status,&e)&&status==0,"wait for real backend removal");
 unsigned long long after=available();require(after>before+16ULL*1024*1024,"actual Btrfs available capacity recovered");
 done(call(a,"UnlockConfig","('" CONFIG "',)",0));g_dbus_connection_close_sync(a,NULL,NULL);g_object_unref(a);
 printf("{\"evidence_kind\":\"disposable-vm\",\"available_bytes_before\":%llu,\"available_bytes_after\":%llu,\"capacity_increase\":%llu,\"number_floor_preserved\":20,\"own_retired_pair\":[%u,%u],\"snapshot_retirement_certified\":false}\n",before,after,after-before,pre,post);
}
int main(int argc,char **arguments){
 if(geteuid()!=0||!getenv("MAHO_DISPOSABLE_VM_TEST")||strcmp(getenv("MAHO_DISPOSABLE_VM_TEST"),"1"))return 3;
 char product[128]={0};FILE *f=fopen("/sys/class/dmi/id/product_name","r");if(!f||!fgets(product,sizeof product,f))return 3;fclose(f);
 if(strncmp(product,"Standard PC",11)&&strncmp(product,"QEMU",4))return 3;
 if(argc==2&&!strcmp(arguments[1],"--owned-extent-case")){extent_case();return 0;}
 GDBusConnection *a=connect_bus(),*b=connect_bus();char text[512];
 guint32 pin=create(a,"@a{ss} {}");
 snprintf(text,sizeof text,"('%s',uint32 %u,'Protected before lock','timeline',{'important':'yes','maho.known_good':'yes'})",CONFIG,pin);done(call(b,"SetSnapshot",text,0));
 done(call(a,"LockConfig","('" CONFIG "',)",0));
 require(protected(a,pin),"promotion before acquisition is freshly observed and preserved");
 guint32 ordinary=create(a,"@a{ss} {}");
 snprintf(text,sizeof text,"('%s',uint32 %u,'Concurrent promotion','',{'important':'yes'})",CONFIG,ordinary);
 require(call(b,"SetSnapshot",text,1)==NULL,"concurrent metadata promotion excluded");
 snprintf(text,sizeof text,"('%s',uint32 %u,false)",CONFIG,ordinary);
 require(call(b,"SetSnapshotReadOnly",text,1)==NULL,"concurrent writable conversion excluded");
 require(call(b,"SetConfig","('" CONFIG "',{'NUMBER_LIMIT':'1'})",1)==NULL,"concurrent retention configuration change excluded");
 require(call(b,"LockConfig","('" CONFIG "',)",1)==NULL,"second lock holder excluded");
 require(call(b,"CreateSingleSnapshot","('" CONFIG "','Concurrent creation','timeline',@a{ss} {})",1)==NULL,"concurrent creation excluded");
 snprintf(text,sizeof text,"('%s',@au [uint32 %u])",CONFIG,ordinary);
 require(call(b,"DeleteSnapshots",text,1)==NULL,"other-client deletion excluded");
 require(!protected(a,ordinary),"denied promotion left original metadata unchanged");
 const char *cli=getenv("MAHO_SNAPPER_OWNER_CLI");require(cli&&cli[0]=='/',"exact VM CLI path provided");
 char *argv[]={(char*)cli,"--no-dbus","-c",CONFIG,"list",NULL};GError *e=NULL;gchar *out=NULL,*err=NULL;gint status=0;
 require(g_spawn_sync(NULL,argv,NULL,0,NULL,NULL,&out,&err,&status,&e),"direct-library probe executed");
 require(status!=0&&err&&strstr(err,"already owned"),"direct-library owner excluded");g_free(out);g_free(err);
 argv[0]="/usr/bin/snapper";out=err=NULL;status=0;
 require(g_spawn_sync(NULL,argv,NULL,0,NULL,NULL,&out,&err,&status,&e),"unchanged distro CLI executed with patched library");
 require(status!=0&&err&&strstr(err,"already owned"),"old CLI ABI stays compatible and respects owner exclusion");g_free(out);g_free(err);
 argv[0]=(char*)cli;argv[3]="maho-vm-owner-alias";out=err=NULL;status=0;
 require(g_spawn_sync(NULL,argv,NULL,0,NULL,NULL,&out,&err,&status,&e),"alias direct-library probe executed");
 require(status!=0&&err&&strstr(err,"already owned"),"config alias shares directory-inode exclusion");g_free(out);g_free(err);
 /* Closing the client connection must release config ownership. A new
  * connection never inherits the old lock or any retirement authority. */
 g_dbus_connection_close_sync(a,NULL,NULL);g_object_unref(a);a=NULL;
 GVariant *locked=NULL;for(int i=0;i<20&&!locked;i++){g_usleep(50000);locked=call(b,"LockConfig","('" CONFIG "',)",1);}
 require(locked!=NULL,"connection death releases client lock");done(locked);
 require(protected(b,pin),"protected snapshot survives client death");
 done(call(b,"UnlockConfig","('" CONFIG "',)",0));g_dbus_connection_close_sync(b,NULL,NULL);g_object_unref(b);
 printf("{\"owner_exclusion_checks\":%u,\"protected_snapshot\":%u,\"ordinary_snapshot\":%u,\"snapshot_retirement_certified\":false}\n",checks,pin,ordinary);return 0;
}
