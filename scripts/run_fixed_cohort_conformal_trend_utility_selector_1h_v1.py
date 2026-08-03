from __future__ import annotations

import base64
import gzip
import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

_SOURCE_SHA256 = "51e0688918ed5a3d10f80f53f60f9f1426abe1b6dc557dacf0fca9b1c920176c"
_PAYLOAD = (
    "ABzY8)DCcJ0{^93dvn`3lK)?y0>`PVNVSq8Id;aQD@~OraW<}<aZ<52yL&npmJ%V06N=;!lx>a2-"
    "~E1#2MNApr!JM)642dfH2Mu>oh4hw`FfY{GQl|uw`r2)%#Y(F_wz7`Wv^$)vfI?pq_E#NzT8CN(tiD2CUI{~<WfJU2}|"
    "oUzUqm5pN8?R9Y2fr1?_mZP4~=~EKcoE>c;^F@HY*58vi!U`Ty?xI3Fk99xR#rEX)PR0GF|!%1x5D0Q2d_!mmZX+9>!W"
    "7JQTJGQPr6k&r`{i8S)}JQbM?WiEm$SV6z{;q14IU;o7~-"
    "m^LLR{l=<(P$k$h+wozHdq9|;&qa3F`Q>24o15?jKX|Bk|GkTJjq7W&FF6G^}e2ed4KWln#g40cT90jjVo$gQ{x3SuBd"
    "TCjazEi9Vcq<&MrS)Uc5W|mH&2jaY;l^{K<N?`sv4D>Ytt-txu1R-"
    "n>0|yE>V!PnOHm$;rw3<jt{obL#c3&%XTi{Q3$=eeaidA4h+`dVlQ=nfL3(<=^y|LGKDc#A_Oiufwg7xxY>O-qGY}I-"
    "2}AIy%0dOlIoue*^gZ@_ifVTLpT0edK_C`ScH3`1lR~>3G`vaDL8z`FzDcU7quQoc#+EC*w))!^JgM>kk=y)YOmo>FH$"
    "1rW1ZTne=Gm282Fp5IqN&ANk4Ar1$C5m4%^?21d;diGkzeN$>BMU(V0on>oYO)%E#jTJX5{+r=gS{ORiA`r_+3MouTaU"
    "M~=91|>@3aD_u6OX%PE(N4@r$p>uoGh6O+A!j{?Ke>3wfk;r}0D3Pq?2w6Ak`elH6^8Q<ek3s_>HNQmy_{cX1S17((8r"
    "m}dEXn-"
    "0nNO@K+(+vY&d3pMgK3%`=8hwj77Xk0@3$&`FeB;QEOg<@D@kXPyKzA_`ytbr}&h4Hgl;NBOl9+e{}NJVhqL`@nDEpn#"
    "vCQWcxE^@<Y}_{u0Kd=@Z}>dl4|u?YAJz`udCAsCa+{!v56PL5ZTxT~RE!F&y~u3g#mFP_`_eu`td_rh)pTR*%y$d`g!"
    "2`^p|M44KBaLSrhVA)^x?vH(6y%mD!!Z;$OtTlm5-"
    "?ysUm;*3kO*mD9v>5e_Ka+KU^Itz`;M(pV1hP`I>K|Vb_xv>nyyC~vYk!Rsb_SFhOxXKqey`hrvO=X!!^@aX;vB<d|^="
    "1lkSkB>$vs5(4xBdeUGXFkE?pv^kR&pn@=FD0M!n<wGh~QR`m*p0jFH_k9_K+rI5|x=JBLW=Nt=f#-"
    "MR`Arp)DcKT8SXp<>@ZhdRUVV4AKb4x^viKcTDIP+?W;S=6A`aQkuDTD#ajFXbuNb4n*NL%;!_MqGBk8s~2$MaPNVfPs"
    "Y=uaxRC{#4hGXld-`VRG8+l7%;9k3T^Qum|h7F9}R<Q&_H{I{YW4+BWB-z7*-"
    "areuaXf2!Q#r_}F)84C{i^L__E>L~m)2jkw1GAv=-<1v@^N6_UyPPzv^yT;_R}C0T#%JsQ$atl-"
    "R0#=)=G81sr%BM~>Lv;UYg3PLYjB}?wvD%r)kCC_wvvk~;+4-"
    "sQF&NF|Nm+RKoghL6$!(wtnYwN(8WL;3BsRDySy^zBtxP!k5g)}UF4~Ot8e&FZ+!rO*YB4gw5K_WwxlHQFvwh&=vqCL$"
    "^Plnd>@r@apZ2FOvWDhYB?9vEv6%HT9zJ<34JSC0E_pV$JqP3Hyq_tIwdvN&>5p<hI0w#lV|Nrt(QX?&*l@$Ty>|tQ_^"
    "Iv#s#=9Bk30FySUq_@h0$*M+C5lmU9mW)e71ChrM-hSp)QaZyAp4n3%*0DsS7<3B4U`EXS`pLhAlk_=5AOt18BDR8b(n"
    "J#xaLJvZYFS=eae^`z|B-n11E`W0ylHILBWQO)Btuv_R!(5WTFGK<ga9*1GMDM2qMh{5_!PsU_LYK-"
    "8hqQp_pGLNmPa!m5?A;;L02J%Y6*(f*QB7k3oSB)v1#x_tzld?C&6na^DRS&b|jutTKvO?DK^Rw-"
    "!DXqgHrfd<RE{vxe*P!w8mF(K4feb8;qqu&n$tM=Jh@$P!0%r1;~>z}30KsE$gwsCuu5Q5_Yjtg3)+$pOu)-"
    "2Xghm9m1wU*WL^(Cf(VNQT*Ni!|Dsu|}d|bA*|LqQ=uKxeEi8!g-(m_D^qEoyJza38Ls-eg1S^pI!P2Z~C!5q5RvdJ>b"
    "?rRSE^z&L9cbmZ%aK^+pXBnN~L@0_OqL)JFy5B9~rYPu<id(TIn$7lzFmp_Z67dui;ek?M+1v+oLK^|OP`3zgxiqXC@1"
    "+H?`^0<IHH*6S!lvS_kM<yJsZ)q7RQSamzXKd1#F@3<~L+ZS&KZS2Rt=juog(rQ38&fkERREkO(sr90mN4$m*0#l|A1}"
    ")sI;mW$mVE!2jwADitFyBq#sZygUXWR4%<ezka<;rgvOLhXzu!&&(mFZJiM0cvb5uDvJQ)yV+a!znMfY`CD>p|<P2oK$"
    "|oD;}e5IUA|ryBku4!654CkqKPs3_IETC%_|cK|A`d#}4GyKa(F2Xhxw@2?CdwA12C9aYC(8$*fRA{@6X#5M^;)Dj~6J"
    "7062=VF`Y$`|M!Rm~mAB&R+YUq;F5TOp)sWv@@L=xSD!;2HYRX{iL(uZ*j?U&06?$oz<j2eH}_JyhqA8tTENz+!?${!&"
    "Cz1z5FH(#@R8k)@!{t6*M}tW!1FqtI<#<{ZdK7lbOh>pW##CDmbo&<G`kxGgYORixVVX)5S*AZtuM2P2NAZzuc(#Qf;q"
    "-%B1Ph;uJlJBi?m$RXvM4t4Nhfv8#eUf{<;&_JXB6%ZNU;YUWLRlaYBExHppY`+QfRBbBJslr4Np>VE!L0J(NnAQ46)l"
    "MnJG%80H<)Qw-J~+1ltk85;xeZ{pe^2%3-PFmSJm>S;8?mn<BMxTl-;b83#j86#`0D2A-"
    "!<^_2Nd?qLb8pZCajB^>u^mIE$HuH9U;P)czv6NHO!Tr)0PeF*Ul{UrlA3lAYm3D?gF6yK|rE{c#QV!ge_Caa3&1;RE4"
    "`%9X^xh%GW5Kn7=|5Dg~H|lh<+5Au{iWAK10X;C&%-W#%KqIT<ds*mcXW3-?dE?w{-nQY8HP5awm2`zORx7^OQ*?72{-"
    "JNUCgel!}<zgg=K1E~u{=#1%dQp3eu(3C|K3h*t|u8_W`_l0D0p|NhtQ#B>kTp=xrsDI<MC!xe+KPAJede${0@~8<uVP"
    "B7m!Yf@$yt-MuqC663j47{%_h^<`yz0sgp2K@C$UleQ6}6wkdnV#4^b&hex`DBH$SV?DRJ~EXM!I%FONPL?N+M>G1q7)"
    "aNr^9Wb~>pC9;4J@Zkr&r&3F{xnrMzZ3q+_E<?BY%#>`&+sVLT<TM45>_WA7VnGK;s$IrP7m0D~pS#^=fzmMzUsDD3;$"
    "YsL2zjg?!E{}@f6wsIxK*5QK0@J0UIUsBVmf!d>qsn|--"
    "_B)XQU!k**>)D0HSpk%KxvmlNTC!5dA)I(9;PU#+qd!WNG1D9F9zm9&V(6tkIo?!b9rO0*2kA{pEC7V#U&XAsn1^koMp"
    "GFzW=Od`U3}S><0nSRP%jrG}2yvL|)z-"
    "TD1x)7iz6|`ch#OgjqY9*`mRA_flMsVc%+Fh|78>G*8#TF0j*)r;)J}l~hOm_)vG%b9TqJJ6Oq5FdsOh)yAjBHspp{cM"
    "B7_`gmqKyym)Ot}cf3qI#&j?a<#}awTbGp?oe#8Xq~UT}<h3_DX8d?$n<Yt))$0jjKt0soI>8(;77ESr6~H^2M`t!cF_"
    "))s9^o6ZK>Gf{Acz4x*l(r+%10R4FnWq}{%CZ_QL$KX@Q>TjETXNp5|RWV9$M0LR0sk6rl~N#E&mtu|uo^E<i<QhD>#t"
    "#|!x80~qe$_x97!<jcp6=u!T4ELt9)KARURn`G4p8}920Ji!tqYCM!Q#EF_Yog9Z18m}!5G`3(4W#6VE@hE%sav~yl@Q"
    "n7TQvHG++G!Nb1e0ijjkEFlVX*SwGz%PceqXFTEGe$QUT)-"
    "q^jh*r_C0yY?uVi0?RfY)%C%%O~&)f_Xl89Lrq<3E9L=DSBf>Ddq3OqU5d%YL|=rcr5lYVEzyvuESfhbH^W19;-"
    "Yzb(&#^mI}s%*d3;m7Et<C|b);Ra8cK4vUWX4Bg)X^S`C{g#t?nyy`>1V}sx#u?h@<puFOoO=6z)ODP&NvG@2t$allyq"
    "2E~?l$m9e_oViF5PfeH`GB~eNeqw=`lz%3R2$!nC2BMEO4I7v;E+#{%{t5qTrBi9=p9e>1!oY|5tlm$CZ{XeL95nY&Y%"
    "CB_mt>2OqQvF!wV$d4oT&r(VUE!vg$iyw(b0aV_(`2gWdi4zz{x=lzze+b>YlBc)<z`gcv{Xig1a$-"
    "Z&MTb_cV`r2WYfmVh*I+>?Y-"
    "X;ygQ!JDs6$Pqy6TVABS6Q7Nf23co}B3|3!?xIou&5sc}IUsD5|X%XOPd%!e>s%ds`#%w`U5P@r>2qLw3DL9gH%LeM?n"
    "Ty>$b(kJp9T#^L{$UKD>cfv&QN|}Ev_^z9d+{ZA19OBd0Qe5@h+hGy&=xJmaBlGG2S!Ico^ah8Hnp9M^WV9b`JqTns2%"
    "Z_2DLF&g1(qOF+$1X#3#eBQU4?;ll2w5t^8>m!GF8VP-Gb8f?DNo7RUqbD4!fCom>3~fS(qAOw6t5_B{9w`S1!qVwU#{"
    "3_&NOo1%;S+SP4ays)MAh;TmqYrXnldRGBT>EO5+Fy&(q#!0n!yH<UKrmOfo`4cn-jj2W;S*u(}QXvmNi4UH$vc7&%IH"
    "^`PvKFCm1#J4Z#=|0(ue^bm?GSlah&rr%8xtZx?`coqrQg^BF`F)eN4_a?=yt@Pv(~phK)fjBa#6x{2?X`6K$y5TdqUJ"
    "h90aeypKLyd>LQpE1u6hq07YY4z@}H~>nfi6eNS}clHY-aThgo>}@3|K#6K7hTn$W0SP<Z}4(Rb&qG5hC<S9_iK(nPqK"
    "wc0Bk$;&v@NP{Z@PS<!Q1cFq!M(yC%jg8XIT-V<msu|4_SXouH!bE=8cO|vA$#&XRA*-"
    "<+D0X_#$gM|qFCCb*9S^D=3BF>y4ODn)>%2D}FuSrOvBao+ikHSD9V?JA^(m$M%1J*^E?!JlFb7>wYwwW&pUeYjZ^-"
    ")9$J2wxQ)~5pn;vBwPe4yZ*0!*mKbpGo$+RTwyi-ZeAM3TH1%9R@T()_;+XUt7Q?sz`?N+j+`HOnD-k_UWTLv}%uFmcu"
    ">TY9q{-S>GL0*f81M|na<eW}-"
    ">r;c0v?XhGw;)+n7`b>=G0#^w153d)*64o}glon*X&&cnK4%_Rtpv_J^RQd>VXpSjknQ<HnD=$dZP5Eaks$`W&@%u4"
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
