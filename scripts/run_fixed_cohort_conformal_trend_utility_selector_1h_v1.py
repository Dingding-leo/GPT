from __future__ import annotations

import base64
import gzip
import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

_SOURCE_SHA256 = "b6e859ab244aeaf8a7d85c46fae1a2a08085c9e413f983d61f56899d5f26f014"
_PAYLOAD = (
    "ABzY8>JV^h0{@j-dvn`1w*OzB0+*dTk>*N@<k+dJ9c9K%oQ-"
    "E&Clh<Kcdyoir9{YLLy=s9vaP!Q?)P`_Ai<aHcG5%y&I33&Z(yAzTgLf%m+vycISaRGlI6^g<0SX<Fo|WaXUDSJ)X$`_"
    "-y2_UqHt+Hf0IevTNAm|&uPNa`hrhAk?+$mzP00L@xGuP@3!fl`I5z{9ZLN;zySWFK~Lk~raAx5&X4nP^8LY*xzEB}a1"
    "3x6`>EU{c?&R~ZY=y-"
    "<g1N>Ph!D0$u8q7u!@8nvP`6rzvrpQWGHhHRKW`Ry^m+VUi|V;e({0LnYZ$H(vL>#@IeHlRk8sS{1dN}Y>VMM6LB!w<z"
    "W=&`;iopSmjAJnr=pSQ?K{!{OgB{_t!)w6Te}KYie9k<C+>TsBuM&8*1EA!|pgydw+KM`SRlZ*)ROpvx`e2dg4#ktJP0"
    "G22=m^^k{v0boA!!$=lV*bbYd1o=#3q)+cX{#hX*FcYXHtujkiSK<axxzyCD)`_+eQZ^*n~E-"
    "wG3KL))k0MT00V0;~Jh0OhJ+V_qoN7K>d$I;R8^<*+rfBp}^=a(PaK;J6R)9WJ#^y}w;5aZ)F{HNn-@8kJ7|M|-"
    "m|9pAQ|8e$DOq`4-y^j~yT=5?=`l+cO@zc}EkWDB2bTaAD#tjJl)F65eFhBB>qe<`c=PL_CKMjnU8`1)fk0-"
    "sqUw%D5`(WnGqOPvbzYxRY-me#z{LAO7i|dPT=NLJi^m@HOtQnLjiNh5Ri7cUi=SMp+BPAcO(L1)>=R(eU4FBcgAqOHs"
    "jRWYt)UZP)Vo65m%T*Z8Kl+ixn56UnF7|SMoe_)_ut6VZF6Vu3NC!0Y1_MPm6R_c!^%ed9Vcx%DZ!i||DhWj2+vV%gDM"
    "YQ;8icnvl78y%qr?wpdUa}@GS6l%HDlysx$%!q-"
    "dc>ocq1MR5ld6qVV`V&rc8dwTF76*m^6I?9Ahs62D<$ogjrvI*o}$@SRm|AeGW<#ZSIO<u^O`iKVHFHWFN|w<uew>Imt"
    "9ozZCa49mA(&nZK{>5yOyad@D4jLK-qU@gWP~v&0+_pz-$Da@xWdhH-xtB@$;`lEt1A07`f48O~91tLZE>DjTt*lN<J$"
    ")d%_X^yJ1aAl^k0--<j7SF*1-1mP-Q;Pi${#y1r<kLrW|^J0;6J?hOA<glE>8E2_zj&J=39%TM~kleRm5v}A-"
    "WX+ki5QKNzoDspTATP@;GGC^$1?(YB$RsK=Peueds#~=gxr_3C7(-h^oV5}`vdhz5uJy1c9T=n$j&<j-"
    "#qOBUFIHnX%+0^$GL_QIwNohup+a*wka8djw_!e?!W9)mDO|mP6Nh^b<a{!o9+h)BoF;ZLKbnjU#-"
    "Orj4vWFU^+usBp2VV8!oyFqKs9Kfy~2JZkeU&*Z+{Fc46I+FpeO=hzAQfWT^hr>;55+?It<ZU+G8W`u|UX<WI@4>4`zj"
    "AGC!1peIu87o@GhaUwe;+^b;#qW+>y}*K3S<1=mQ#P3r8w=8S^S3%O*;JzFKaIJe}PPH#4Xe*7+C%*J`<ukw;_ohKYhA"
    "RZQz8{(}4Ym#+Ajiw3=3iZMjF0nfJn@~uz#6Pn__!U3!bARD&Ln)E5arhvSAxcT_Mjcy-Ff-Af=A|b?{Cs>dLz7KEv6A"
    "eeMFhJvLR^Kzhp}(rEdozTWAbM?7lep+vXsPIrMQN@^0?6Q`XMYlHRIik^MtERwXeg%8qp`O=raWhxej9rg$ijf_M-"
    "?M8fQ!MdXT+i6EpGBJt(vk?j9$KIH`zfJ_tE7%)>juR2o5>Q8d?K&Q0`~7ooA4MVYN5ZD{~E^C=CSB(e$IOsodQGIY2E"
    "up2jr&I-##bbyxYE0@p#TCUCrBFzM{X~5}-"
    "Iy1|=aVFu%FuzQasPy+LD?q^J$|d#7eGDx_ja%8rpg@P})Jc^4YmjjEcaTK6?*<8H-"
    "vcLL7{x61`9g(T3!f@NE4(nigEzrh!+-"
    "c;1QV=inNh$wS#%#uR?d+lAO2lri6c5v{PASq>fB*eM<rZTz1PF2j*3*cDxh2P0`uzX-"
    "_2Piw<qye)>s4Rb);A%!)&)jF6+%$BU`Y6dgh?0@ia^B!a(Iw-sivluQ#ktV=LbUQS`39e7>&FE`5bJ{ZyYosG`KGHR{"
    "zsRUQM_&PWB<mZ&-uNq-"
    "F&=}tE$qSpb`)JGZNBA1?DPu<id(FjVj7sjp{p_afhduafwkqS{}ZPQ2~uOf*brq=~rCz`?Lg-Wy3(E!e0ZMukd0oREp"
    ">va?&V>79oax0*yimobTtXdA?@6?BocU)J1?abRj8~gF^xjNE=v>H&2^EaR+m7<(Qe!D2<5w9VHz|@L^LCb2^aAjR&F#"
    "ik%+Ug++#tOQrJXMM%<#3yRfqaw>vRwHtW6e&`88#8D&oT`oi|9_(H-qzAW-"
    "1?QW9I~@1Be}LT`yW!M|kNLc1|#BLFi!PPBnZ+9By}8PF50TP*W;CwPb-"
    "`?f_I=7hiW(mT!_$D{&W76Rr#>wA13Fj;iCYjia>OA|$sf#5M^;)DkBAJ72Fn&&4*)l|RtUqMA#RNlpzZzKoL9_d-"
    "b35?h~O(O#@5!87!s(^3hnUl~_(KZg-Skogf44`Q_=dMJ}2H56t`0cL_l{!&Cz1zELI(#@Ref~BAqs9;``tW&<&qtN|T"
    "<{ZdKS7s{0>s)1ACDmbo&<G`kxGgwWRixT|X)5S*AZtuM2P2NAZzuc(#Qf;q-"
    "%B1Ph;=XFokVa&<dE`BhdTJMKopOBFYwnv&_JXB6%ZNU;jfJ9tbE@NTeJyq*nSh{soLG4Q-z5lO5t4lf-"
    ")m8nAI9N)s`j2H7ZFK<)Qw-K00lAR%kk_wB?y?q*GydH+6C-&-uOfM(mr&XazI&??=0)#j86#`0D2A-"
    "!<^_2UOV1Lb8pZZm5fz>yS+oE$HuI9U(%Qczv6NHO!Tr)0PeF*Ul_8iJ<|IAYm3DE(6g2C?HWmYmD~nge_Caa3&1;RE4"
    "`%tu~YD%GW5Mn7=|LDg_o5C$HnALuB3$Kd@_&!TUnw%FIWIb240NvFqMl7w#XH?;q?d(j@%zG0e+q_Ya7tFiLlrmghp1"
    "?%<CK`O#=Z|Ib?gGLX7RgwB|DBXvH^O-"
    "Wfup$OkX?F#98dS3|q3ypPCo~kLU<_c+1MEx75PY5L*`zaY#)w8Z4kw;DN3Hy3f6kh3a;?>RK73GpRV@!E9yhp=k@v18"
    "~cn<HmApabGSJZwE@0p0J&`az==?2E)A+JbqQT0akI_cU8Eg1smDv6j$77(OzBqhGg+3BPnc#Kkqxow2hHseu%Yoa;wE"
    "D)hul(QR68#8+gr=nPcZY7Kk*_X3#XEuZm9Y5zXDz(^Hvg#y}e;?PyQU5-"
    "R$YsL2zjg?!PLGP<6wsIxK(P`L1*TI)b3oV#u;2JGqw0KI-"
    "_B)XQU!k**_IZWHSpk%KxvmlNTC!5*LveLK1^Xw*I?t{kV^KIUJT65m<coLLYqS<<`%`?agQ(IK4t2!irXp-Qp3FfILm"
    "HTjsHc>^al>u*bf4tspk9MXr#UTh`hWvv}zSpZnj$Sba#IggjqY9*`mRA_fp(bVc%+Fh|78>G*9=kF0j)Yr;)J}l~il|"
    "_)x3Wb9TqJJ6Oq5FdsOh)yAg|GvtPPcMB7_`gCSmt>)fhu5M^FQ$18(JLvD1+zlF8D4z?G#z)R-H$?i&-"
    "VF`fo%)lawY2H0aW$zgRjV^{+JlCl_3(}>Up!kU+_W>VcJ100Q9p*Sm<YG#AnNIP>W3Lbl_Il2+U;BS)=ZW4%L6jECC+"
    "4-<kkmCModuwI38C0?8?VT`c9{7wGmsN-_f0n%A2Qdz3XqoXwO4cUfAap&b&#gFl*jOxL1y)eqz3^vJPN*Cr_3D*y;<3"
    "Dx{lE)fTH=6LmKlU=z25Xvw;2Amxhab`%+xx<0#C332V=L!)QN?VSxb$5L<G=$er`DOL$tE8*O7hudVX1+1_k6)+A#s!"
    "G0l+H3)A!z5@HSho47t`MGWG@f66H~^!XYU*}bEgtZ6w^swY_p>eErI=hy^ks-*-"
    "DoyxiH1aF(Y!sm86K(=7tI@#Mh{Zli6}|Q<D2Sj(Y#5iBkf|<P?Ed#I()Dwblc3zrz<yYbzh;|M{ToIozV)8I7-"
    "j<B6+h<;U0txWux%-&dRJixsONcvWlHk8LO);Ccz*IRCrJ>iBggnmB;-"
    "CZmIB3UZZRrNqC#UNou0x9zjLjaT1Xjx!&mL_!EBQ%$9VaESBTc|AUGb(S-"
    "@8{7Sdp`YlNz)sJN^2CYHPwfZjAU22+%Ox)6iGXgU+O{RLTSKm<Ke?uYvQo8wC8-&s-"
    "H>1*~r7|ics2kXKUg>POJEI^Yn>JQPl$t+j@BfzI-SLdLv<0e;_M2ON9B#E)jJCq#Wti3e7cKP7;SL!|jSIR&^}D-"
    "XuG>^%K7`>~j;#r2Hgj-;0-"
    "Zw=wH(<BdIi@Ig6;w5stb*kK9T3(k}N<#<|(we6DERJ%KTfwcinX4K86Y85TCx9;;QG~4vUyaZxq8AnO6tMDodoK$1rr"
    "%q@t=Nqy1>>K_I(9@XWYO$r;KnumqXnCRv$SK>d2?Dh#ZXtO^{NAJE;AsXBh|7L=}MpNFoh0xiDfu$!5Oi4k&@g{cunO"
    "S|=b663sb<&vydYsvGBpVLo4P>6|#l~7cvI!M|YuHklTDzef|mD!@r0>=#18*)GZ-"
    "0qoq%xKeX>C;u$u#LLOm;t+iO>7W?h74KJ(0IaZM|i4ngKXL4gA7GQeEWi)?vuUzH^qD<Gkq@k45i$Wo0(3gKQ)peb)O"
    "2K-#2Odp!F8VyGtN3{p#0TkHMBqJk<BnUQ4&1OeGL2YOYfhP-VUKQxN?v1f`Pcs`t=wk<d>k|INyfsb7eU^clEev%=aq"
    "%)-n6nR}5kaVGB6ghuUx!t>ok-"
    "=DX}>~|Bd_Dt}liEuM(wO2ZlmvN|(23G={uJKF=1gUV1+QF?G8>OAOvcEZ0Gn%)kvZ`o>iTtMTN@|aU?X;^xR%1I*?DU"
    "|KTaWBsIxuTH9#lONe8qShsPNR*d2hTVc4bLoiBb6!Pku={Rv=^QQ%d)xlYS{&JYB3{4!WS$-"
    "Xj4%nU~1kkoBvtm<NqF&*~vHy^c1XfS!r0ZDBcoG<D^ZX-U|5r;?mM)@w@({7gr<Z1Z-v3Cd@nhOzDKR<fk|i+Z=-"
    "pqpA-1~vavo!vv!-"
    "Nx?xMg87`Yb_oR%pdELb2{Cv&kah_maNs?f@D=;<l<GuJYU@mECth8qo@7hnsH8=$2ptNna5QtfpgEiuvUGTt35Pid;S"
    "pSecf^!^!^`>m2eALGXMY"
)


def main() -> int:
    source = gzip.decompress(base64.b85decode(_PAYLOAD.encode("ascii")))
    if hashlib.sha256(source).hexdigest() != _SOURCE_SHA256:
        raise RuntimeError("embedded strategy research source hash mismatch")
    with tempfile.TemporaryDirectory(prefix="conformal-trend-utility-") as directory:
        path = Path(directory) / "run.py"
        path.write_bytes(source)
        previous = sys.argv[0]
        sys.argv[0] = str(path)
        try:
            runpy.run_path(str(path), run_name="__main__")
        finally:
            sys.argv[0] = previous
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
