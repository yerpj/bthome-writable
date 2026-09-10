/* AES-CCM composed from Espruino's native AES, for tools/ccm_bench.py.

   One statement per line, deliberately: the Espruino console evaluates a pasted
   line the moment it ends outside a bracket, so a wrapped statement is executed
   in halves.

   CCM is a CBC-MAC for the tag and a counter-mode keystream for the data. CTR
   is not used to produce the keystream -- this firmware ignores its `iv` and
   always starts from a zero counter block -- so the keystream comes from one
   ECB call over the concatenated counter blocks, ECB encrypting each
   independently. */
function hx(h){var a=new Uint8Array(h.length/2);for(var i=0;i<a.length;i++)a[i]=parseInt(h.substr(i*2,2),16);return a;}
function sx(a){a=new Uint8Array(a);var s="";for(var i=0;i<a.length;i++){var b=a[i].toString(16);s+=b.length<2?"0"+b:b;}return s;}
var Z=new Uint8Array(16);
function ccm(pt,key,nonce,M){
var L=15-nonce.length, n=Math.ceil(pt.length/16);
var b=new Uint8Array(16*(n+1));
b[0]=((M-2)/2)<<3|(L-1); b.set(nonce,1); b[14]=(pt.length>>8)&255; b[15]=pt.length&255;
b.set(pt,16);
var mac=new Uint8Array(AES.encrypt(b,key,{iv:Z,mode:"CBC"}));
var A=new Uint8Array(16*(n+1));
for(var i=0;i<=n;i++){A[i*16]=L-1; A.set(nonce,i*16+1); A[i*16+14]=(i>>8)&255; A[i*16+15]=i&255;}
var S=new Uint8Array(AES.encrypt(A,key,{mode:"ECB"}));
var base=mac.length-16, ct=new Uint8Array(pt.length), mic=new Uint8Array(M);
for(var j=0;j<pt.length;j++) ct[j]=pt[j]^S[16+j];
for(var m=0;m<M;m++) mic[m]=mac[base+m]^S[m];
return {data:ct, mic:mic};
}
