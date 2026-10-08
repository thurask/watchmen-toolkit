/* atx: seekable reader for apitrace (snappy container, trace version 6) files.
   index: full scan, writes sig table + one checkpoint per Present.
   dump : starts at a checkpoint, prints calls like `apitrace dump`. */
#define _FILE_OFFSET_BITS 64
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
extern int snappy_uncompress(const char*,size_t,char*,size_t*);
extern int snappy_uncompressed_length(const char*,size_t,size_t*);
enum{T_NULL,T_FALSE,T_TRUE,T_SINT,T_UINT,T_FLOAT,T_DOUBLE,T_STRING,T_BLOB,T_ENUM,T_BITMASK,T_ARRAY,T_STRUCT,T_OPAQUE,T_REPR,T_WSTRING};
static unsigned char*B;static size_t Bcap,Blen,P;static FILE*F;static int eof_;
static long long last_fpos=-1;static size_t last_bstart=0;
static int refill(void){uint32_t cl;static unsigned char*cb;static size_t cc;
  if(eof_)return 0;long long fp=ftello(F);
  if(fread(&cl,4,1,F)!=1){eof_=1;return 0;}
  if(cl>cc){cc=cl;cb=realloc(cb,cc);}
  if(fread(cb,1,cl,F)!=cl){eof_=1;return 0;}
  size_t ul;if(snappy_uncompressed_length((char*)cb,cl,&ul)){eof_=1;return 0;}
  if(P>0){memmove(B,B+P,Blen-P);Blen-=P;P=0;}
  if(Blen+ul>Bcap){Bcap=(Blen+ul)*2;B=realloc(B,Bcap);}
  if(snappy_uncompress((char*)cb,cl,(char*)(B+Blen),&ul)){eof_=1;return 0;}
  last_fpos=fp;last_bstart=Blen;Blen+=ul;return 1;}
static int ensure(size_t n){while(Blen-P<n){if(!refill())return 0;}return 1;}
static int ERR;
static unsigned gb(void){if(!ensure(1)){ERR=1;return 0;}return B[P++];}
static uint64_t gu(void){uint64_t v=0;int sh=0;unsigned c;do{c=gb();if(ERR)return 0;v|=(uint64_t)(c&0x7f)<<sh;sh+=7;}while(c&0x80);return v;}
static char*gs(void){uint64_t L=gu();if(!ensure(L)){ERR=1;return strdup("");}char*s=malloc(L+1);memcpy(s,B+P,L);s[L]=0;P+=L;return s;}
/* signature tables */
typedef struct{int seen;long long defev;char*name;int n;char**names;long long*vals;}Sig;
#define MAXS 20000
static Sig fn[MAXS],en[MAXS],bm[MAXS],st[MAXS];
static long long evno,callno,frame;
static int printing;
/* string builder */
static char*sb;static size_t sbl,sbc;
static void sput(const char*s,size_t n){if(sbl+n+1>sbc){sbc=(sbl+n+1)*2;sb=realloc(sb,sbc);}memcpy(sb+sbl,s,n);sbl+=n;sb[sbl]=0;}
static void sp(const char*s){sput(s,strlen(s));}
static void spf(const char*f,...);
#include <stdarg.h>
static void spf(const char*f,...){char t[256];va_list a;va_start(a,f);int n=vsnprintf(t,sizeof t,f,a);va_end(a);sput(t,n);}
static long long cur_no;static long long*bcalls;static int nbcalls;
static int bwant(void){if(!bcalls)return 1;int a=0,b=nbcalls-1;while(a<=b){int m=(a+b)/2;if(bcalls[m]==cur_no)return 1;if(bcalls[m]<cur_no)a=m+1;else b=m-1;}return 0;}
static FILE*BLOBF;static long long blob_min=0,blob_max=1LL<<60;
static uint32_t crct[256];static void crcinit(void){for(uint32_t i=0;i<256;i++){uint32_t c=i;for(int k=0;k<8;k++)c=c&1?0xEDB88320u^(c>>1):c>>1;crct[i]=c;}}
static uint32_t crc32z(const unsigned char*b,size_t n){uint32_t c=0xFFFFFFFFu;for(size_t i=0;i<n;i++)c=crct[(c^b[i])&0xff]^(c>>8);return c^0xFFFFFFFFu;}
static long long rsint(void){unsigned c=gb();uint64_t v=gu();return c==T_SINT?-(long long)v:(long long)v;}
static void val(void){unsigned t=gb();if(ERR)return;
  switch(t){
  case T_NULL:if(printing)sp("NULL");return;
  case T_FALSE:if(printing)sp("false");return;
  case T_TRUE:if(printing)sp("true");return;
  case T_SINT:{uint64_t v=gu();if(printing)spf("-%llu",(unsigned long long)v);return;}
  case T_UINT:{uint64_t v=gu();if(printing)spf("%llu",(unsigned long long)v);return;}
  case T_OPAQUE:{uint64_t v=gu();if(printing){if(v)spf("0x%llx",(unsigned long long)v);else sp("NULL");}return;}
  case T_FLOAT:{if(!ensure(4)){ERR=1;return;}if(printing){float f;memcpy(&f,B+P,4);spf("%.9g",f);}P+=4;return;}
  case T_DOUBLE:{if(!ensure(8)){ERR=1;return;}if(printing){double f;memcpy(&f,B+P,8);spf("%.17g",f);}P+=8;return;}
  case T_STRING:{uint64_t L=gu();if(!ensure(L)){ERR=1;return;}if(printing){sp("\"");sput((char*)B+P,L);sp("\"");}P+=L;return;}
  case T_WSTRING:{uint64_t L=gu();if(printing)sp("L\"");for(uint64_t i=0;i<L;i++){uint64_t c=gu();if(printing){char ch=c<128&&c>=32?(char)c:'?';sput(&ch,1);}}if(printing)sp("\"");return;}
  case T_BLOB:{uint64_t L=gu();if(!ensure(L)){ERR=1;return;}
    if(printing){uint32_t h=2166136261u;for(uint64_t i=0;i<L;i++){h^=B[P+i];h*=16777619u;}
      spf("blob(%llu,fnv=%08x,crc=%08x",(unsigned long long)L,h,crc32z(B+P,L));
      if(BLOBF&&(long long)L>=blob_min&&(long long)L<=blob_max&&bwant()){long long o=ftello(BLOBF);fwrite(B+P,1,L,BLOBF);spf(",at=%lld",o);}
      sp(")");}
    P+=L;return;}
  case T_ENUM:{uint64_t id=gu();if(id>=MAXS){ERR=2;return;}Sig*s=&en[id];
    if(!s->seen){s->seen=1;s->defev=evno;s->n=gu();s->names=calloc(s->n+1,sizeof(char*));s->vals=calloc(s->n+1,8);
      for(int k=0;k<s->n;k++){s->names[k]=gs();s->vals[k]=rsint();}}
    long long v=rsint();if(printing){int k;for(k=0;k<s->n;k++)if(s->vals[k]==v){sp(s->names[k]);break;}if(k==s->n)spf("%lld",v);}return;}
  case T_BITMASK:{uint64_t id=gu();if(id>=MAXS){ERR=2;return;}Sig*s=&bm[id];
    if(!s->seen){s->seen=1;s->defev=evno;s->n=gu();s->names=calloc(s->n+1,sizeof(char*));s->vals=calloc(s->n+1,8);
      for(int k=0;k<s->n;k++){s->names[k]=gs();s->vals[k]=gu();}}
    uint64_t v=gu();if(printing){uint64_t r=v;int first=1;for(int k=0;k<s->n;k++){uint64_t f=s->vals[k];if((f&&(r&f)==f)||(!f&&!v)){if(!first)sp(" | ");sp(s->names[k]);first=0;r&=~f;}}
      if(r||first){if(!first)sp(" | ");spf("0x%llx",(unsigned long long)r);}}return;}
  case T_ARRAY:{uint64_t n=gu();if(printing)sp("{");for(uint64_t i=0;i<n&&!ERR;i++){if(printing&&i)sp(", ");val();}if(printing)sp("}");return;}
  case T_STRUCT:{uint64_t id=gu();if(id>=MAXS){ERR=2;return;}Sig*s=&st[id];
    if(!s->seen){s->seen=1;s->defev=evno;s->name=gs();s->n=gu();s->names=calloc(s->n+1,sizeof(char*));for(int k=0;k<s->n;k++)s->names[k]=gs();}
    if(printing)sp("{");for(int k=0;k<s->n&&!ERR;k++){if(printing){if(k)sp(", ");sp(s->names[k]);sp(" = ");}val();}if(printing)sp("}");return;}
  case T_REPR:{val();int sv=printing;printing=0;val();printing=sv;return;}
  default:ERR=3;return;}}
/* pending calls */
typedef struct{long long no;int sig;int used;int na;char**a;char*ret;}Pend;
#define NP 64
static Pend pend[NP];
static Pend*pfind(long long no){for(int i=0;i<NP;i++)if(pend[i].used&&pend[i].no==no)return &pend[i];return 0;}
static Pend*pnew(long long no,int sig){for(int i=0;i<NP;i++)if(!pend[i].used){pend[i].used=1;pend[i].no=no;pend[i].sig=sig;pend[i].na=0;pend[i].a=0;pend[i].ret=0;return &pend[i];}
  /* evict oldest */ Pend*o=&pend[0];for(int i=1;i<NP;i++)if(pend[i].no<o->no)o=&pend[i];for(int k=0;k<o->na;k++)free(o->a[k]);free(o->a);free(o->ret);o->no=no;o->sig=sig;o->na=0;o->a=0;o->ret=0;return o;}
static void details(Pend*p){for(;;){unsigned c=gb();if(ERR)return;
  if(c==0)return;
  if(c==1){uint64_t i=gu();sbl=0;if(sb)sb[0]=0;val();if(printing&&p){if((int)i>=p->na){p->a=realloc(p->a,(i+1)*sizeof(char*));for(int k=p->na;k<=(int)i;k++)p->a[k]=0;p->na=i+1;}free(p->a[i]);p->a[i]=strdup(sb?sb:"");}}
  else if(c==2){sbl=0;if(sb)sb[0]=0;val();if(printing&&p){free(p->ret);p->ret=strdup(sb?sb:"");}}
  else if(c==3){gu();}
  else if(c==4){uint64_t n=gu();for(uint64_t k=0;k<n;k++){uint64_t id=gu();static char seenbt[1<<20];if(id<(1<<20)&&!seenbt[id]){seenbt[id]=1;for(;;){uint64_t t=gu();if(ERR||t==0)break;if(t<=3){free(gs());}else gu();}}}}
  else if(c==5){gu();}
  else{ERR=4;return;}
  if(ERR)return;}}
static const char*filt;static FILE*IDX;
static void save_sigs(const char*path){FILE*o=fopen(path,"w");
  Sig*T[4]={fn,en,bm,st};const char*K="FEBS";
  for(int t=0;t<4;t++)for(int i=0;i<MAXS;i++){Sig*s=&T[t][i];if(!s->seen)continue;
    fprintf(o,"%c\t%d\t%lld\t%d\t%s",K[t],i,s->defev,s->n,s->name?s->name:"");
    for(int k=0;k<s->n;k++){fprintf(o,"\t%s",s->names[k]);if(t==1||t==2)fprintf(o,"\t%lld",s->vals[k]);}
    fputc('\n',o);}
  fclose(o);}
static void load_sigs(const char*path,long long upto){FILE*i=fopen(path,"r");if(!i)return;static char line[1<<16];
  while(fgets(line,sizeof line,i)){size_t L=strlen(line);if(L&&line[L-1]=='\n')line[L-1]=0;
    char*f[4096];int nf=0;char*p=line;f[nf++]=p;while((p=strchr(p,'\t'))&&nf<4096){*p++=0;f[nf++]=p;}
    if(nf<5)continue;long long de=atoll(f[2]);if(de>upto)continue;
    int id=atoi(f[1]);Sig*s=line[0]=='F'?&fn[id]:line[0]=='E'?&en[id]:line[0]=='B'?&bm[id]:&st[id];
    s->seen=1;s->defev=de;s->n=atoi(f[3]);s->name=strdup(f[4]);s->names=calloc(s->n+1,sizeof(char*));s->vals=calloc(s->n+1,8);
    int hv=(line[0]=='E'||line[0]=='B');
    for(int k=0;k<s->n;k++){int j=5+k*(hv?2:1);if(j<nf)s->names[k]=strdup(f[j]);else s->names[k]=strdup("?");if(hv&&j+1<nf)s->vals[k]=atoll(f[j+1]);}}
  fclose(i);}
int main(int argc,char**argv){
  if(argc<5){fprintf(stderr,"atx index TRACE SIGS IDX [seconds]\natx dump TRACE SIGS IDX FRAME0 FRAME1 [name-substr[,..]] [blobfile minsize]\n");return 2;}
  int dump=!strcmp(argv[1],"dump");
  F=fopen(argv[2],"rb");if(!F){perror("open");return 1;}
  Bcap=4<<20;B=malloc(Bcap);
  time_t t0=time(0);int budget=argc>5&&!dump?atoi(argv[5]):100000;
  long long f0=0,f1=1LL<<60;const char*filters[32];int nfil=0;
  /* find checkpoint */
  long long ck_frame=0,ck_call=0,ck_ev=0,ck_fpos=-1,ck_off=0;
  { long long want=-1; if(dump){f0=atoll(argv[5]);f1=atoll(argv[6]);want=f0;}
    FILE*i=fopen(argv[4],"r");if(i){long long a,b,c,d,e;while(fscanf(i,"%lld %lld %lld %lld %lld",&a,&b,&c,&d,&e)==5){if(want<0||a<=want){ck_frame=a;ck_call=b;ck_ev=c;ck_fpos=d;ck_off=e;}else break;}fclose(i);} }
  if(dump&&argc>7&&argv[7][0]&&strcmp(argv[7],"-")){char*s=strdup(argv[7]);for(char*t=strtok(s,",");t&&nfil<32;t=strtok(0,","))filters[nfil++]=t;}
  if(dump&&argc>9){BLOBF=fopen(argv[8],"wb");blob_min=atoll(argv[9]);if(argc>10)blob_max=atoll(argv[10]);if(argc>11){FILE*c=fopen(argv[11],"r");long long v;bcalls=malloc(8*1000000);while(c&&nbcalls<1000000&&fscanf(c,"%lld",&v)==1)bcalls[nbcalls++]=v;if(c)fclose(c);}}
  crcinit();
  if(ck_fpos>=0){load_sigs(argv[3],ck_ev);fseeko(F,ck_fpos,SEEK_SET);if(!refill()){fprintf(stderr,"seek fail\n");return 1;}P=ck_off;frame=ck_frame;callno=ck_call;evno=ck_ev;}
  else{unsigned char m[2];if(fread(m,1,2,F)!=2||m[0]!='a'||m[1]!='t'){fprintf(stderr,"not a snappy trace\n");return 1;}
    uint64_t ver=gu();uint64_t sem=0;if(ver>=6){sem=gu();for(;;){char*n=gs();if(!n[0]){free(n);break;}char*v=gs();if(dump)printf("// %s = %s\n",n,v);free(n);free(v);}}
    fprintf(stderr,"version %llu semantic %llu\n",(unsigned long long)ver,(unsigned long long)sem);}
  if(!dump){IDX=fopen(argv[4],"a");}
  fprintf(stderr,"start frame %lld call %lld ev %lld\n",frame,callno,evno);
  for(;;){
    if(!ensure(1))break;
    unsigned c=B[P++];evno++;
    if(c==0){gu();uint64_t id=gu();if(id>=MAXS){ERR=2;break;}Sig*s=&fn[id];
      if(!s->seen){s->seen=1;s->defev=evno;s->name=gs();s->n=gu();s->names=calloc(s->n+1,sizeof(char*));for(int k=0;k<s->n;k++)s->names[k]=gs();}
      long long no=callno++;cur_no=no;
      int want=0;if(dump&&frame>=f0){want=1;if(nfil){want=0;for(int k=0;k<nfil;k++){const char*f=filters[k];if(f[0]=='='){size_t a=strlen(s->name),b=strlen(f+1);if(a>=b&&!strcmp(s->name+a-b,f+1)){want=1;break;}}else if(strstr(s->name,f)){want=1;break;}}}}
      int ispres=0;{size_t L=strlen(s->name);ispres=L>=9&&!strcmp(s->name+L-9,"::Present");}
      Pend*p=(want||ispres)?pnew(no,(int)id):0;if(p&&!want)p->sig=-1-(int)id;
      printing=want;details(p);printing=0;
    }else if(c==1){long long no=gu();cur_no=no;Pend*p=pfind(no);int pr=p&&p->sig>=0;
      printing=pr;details(p);printing=0;if(ERR)break;
      if(p){int sid=p->sig>=0?p->sig:-1-p->sig;Sig*s=&fn[sid];
        if(pr){printf("%lld %s(",no,s->name);for(int k=0;k<p->na||k<s->n;k++){if(k)printf(", ");if(k<s->n)printf("%s = ",s->names[k]);printf("%s",k<p->na&&p->a[k]?p->a[k]:"?");}
          printf(")");if(p->ret)printf(" = %s",p->ret);printf("\n");}
        size_t L=strlen(s->name);
        if(L>=9&&!strcmp(s->name+L-9,"::Present")){frame++;
          if(dump){if(frame>=f0)printf("// frame %lld ends at call %lld\n",frame,no);if(frame>=f1)break;}
          else{if(P>=last_bstart)fprintf(IDX,"%lld %lld %lld %lld %lld\n",frame,callno,evno,last_fpos,(long long)(P-last_bstart));
            if(time(0)-t0>=budget){fprintf(stderr,"budget stop\n");break;}}}
        for(int k=0;k<p->na;k++)free(p->a[k]);free(p->a);free(p->ret);p->used=0;}
    }else{ERR=5;}
    if(ERR)break;
  }
  if(ERR)fprintf(stderr,"ERR %d at call %lld frame %lld\n",ERR,callno,frame);
  fprintf(stderr,"end frame %lld call %lld ev %lld eof %d t %ld\n",frame,callno,evno,eof_,(long)(time(0)-t0));
  if(!dump){fclose(IDX);save_sigs(argv[3]);}
  if(BLOBF)fclose(BLOBF);
  return 0;}
