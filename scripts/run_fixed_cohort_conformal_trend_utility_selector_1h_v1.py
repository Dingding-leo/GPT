from __future__ import annotations

import base64
import gzip
import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

_SOURCE_SHA256 = "e537ad140313d2ec6e7d03fc1a4e2634101a513e55f8cbe8c9b595d2de461f46"
_PAYLOAD = (
    "ABzY8%@1&D0{@j-ZFAc=lK!q=f#cLwq&i8F96RIDmQv+OoQ-Q|oK)=1-"
    "k#Qlr9{Z$gd({FWn1I%f4`^kLV|CyXDXA3Kz9RZG@gC|)>*P;oUeEJE)$%yaGNGs&ipt|az77~SoV6hExS$qObYwG@#Q"
    "88m-h2FnZ&&{iA(*QI;^ZO_|zTwJ`Lkr+kO`B3)%5*o9>w}S)AIY)Q<x+;7=O#H2-"
    "ay^Z)GpI3Fk9AFP=BEX)N*1DCO%%1x5D5cBEA(yv9n+9>)Y7JQTJGQPr4k&r`{i8S)}JQbM?WiEm$Ss}mo@$A=&U;fE2"
    "KCn6SR{l=<(P$k$h+wozHW&o|#Ooy6qB+k*9E^5(7=`(MBt;}vd6JE$o6+6W>wP=_`r+dJHHpc@Z|LG$8duV|mc|QdTu"
    "I|b8n@E0I!@BwpIv^wym){13;*@(;*x}(_>=W&_0x~R)IU8vTAv;ry?J}`c6BmcpDdTBlarJ6$(v*G=G5z5pMCx7`Slf"
    ";`rgm)KaKu=_2JqZGVhm*%fIQ5LGKDgG}km3Ux!;EbAOxmy`#y|bTs*KbaZ?@natFm{{!*)<%c%Xw~F-"
    "i`p6;u`uQI;@bMe|)A6+T@%)_s{N;*&zC7puIQu6$PR5ho$BS#O#vd~JsihzB)6>b2O(*<xGU?I64GI0!B)ShYKk}2KN"
    "$>OLD@#K^4UOs>(gco=C%wO4emy_?VEW9YuCC9&(16FiUoS5Cm(N!h*B9T;(Q-"
    "QJ^?HF=GZ;}4hbwFnorM0KAMM19jC{aG@7Qvm3pwjC{FjS|9E?OY4q*3E(+-"
    ")4B^^RvuEKEs(T^nBB<=rqv6u7fjA*358T7H|a^Clbv_Ug(Fi>(cfioPlzLNhx%==gD4aOo~C4uOByL>%5g{t*jgYXtx"
    "(og+;l=#6+&rZ!#=Gn}ZW)AsSZv3N@x0Yit-iQYy#L86Xuuo@yrjGoOwTQpOVbb!6aE!GG9MJ9eAk6yu!!A@j-"
    "~{6Qsn0>lqK~_hSj@)Ez>ilrF0v0}%kmiu<D7IFs9$RII2{91vdrIC)`({4G`<y@Q!x!0?f8%dz$`Hb1!TNEwj*tUg<;"
    "%ZMTx{7mtwKz1ccIUduHS)xz%zOnw5>%(a8;a&FYPOdU|qWClK$Vh;K!ng)7-"
    "tBLv|pUtsr!O2;>qVII{7{pZCZ=epIKDav8lhds_x(QM!P4?M{H`yjb*;UZbdoyeL!Yaxj5w%H?sTR|wxEi+%HvW4s+P"
    "3TBedY+65uvNEeF>)8>{V;~LgxG7Pf@GJcyIk90O*=S{MmZMFaTdFMLcf@e8DVbzEvKoBX0Ab{XoLyP0U%{V6mG+OJ_Q"
    "sNO(~#W0K@_Bft*jq)1$I42WVmy^P|bwa11Jw<~T8!xLzo%#gmxyN_hBbCa4+>wO5=U38tpU?Ass1$^aHu$SH~doG<f_"
    "eOJb?t~f0;gbhRWR`%Gado19xBUwnW?SomNnamHRVBZKb&$BGa`fKmeh<;+l%#37g{CbTxuNXBFaZ@_`uQ?+p^ukfH<e"
    "sgPU7TC-OoulcK|g*MF?!=X^H+H}ZhcGuN+2E<lN%aaJJuxYq8d#V84T)$GhAYJz?)D=GsQnML*R-"
    "Z__@FEwxN`W*f=mqWbjhbyHVQ~!p%%H(!6wMXgnWZ%*bTZPplMsXcECLjo?=S_&Draphe&*ZA|{`$b}#pJ6TE^TZOo0c"
    "!jvI^7<w$Jk{gfjPr!6NVTus!W!Nuuh=s=3b_tra)pX%F!rMe2#vj^e%;94v5Dz;=^7MU3b@CP!cQt;dK|bM8Rp@gU@D"
    "BD#VDEUFz3d5%nR4pjH1la5w<jloAHz;P7>K9ZU$C^Vj9|Ag4p$&LuZENBsxgT`IS@XAT4KS6p>~E(KP6^N1d7J-"
    "8h}VG4wB!Br5S<MFnu!TtQO5T*uH3sCg^v7!>R<ow|r}eGL)L`VNXH*WD1|tb5=%3}cwZI$vmTYvEHyXq6YncR&;DHSo"
    "g^BOJksl^Fw^(~0h5$_gAg;^E&#mN=>-"
    "!yiuuuFV~0bxgu#)oVS>>X=AnR7G@4C@`<i{@t8aVtZ15WsWt1UPp*UI?Q%k#IoLuHKGOUsAmp~YEQG|E(}y0<$eC!|9"
    "Zn}H<t2UkVNn5%jfHQ@6uO%(@*sdxGD;)TD@M4RK+o%?etWDwnXKj2>NTh2zR<U;k^#9rasaLm$^iK-"
    "E~vfM8he~Ug*1Of?6EQ?4=H<CMralwM`>|xQaA>SY8)#U1)|gFI1SNwgz<mYSSgOi?}W{S+AoI5t|9+6s$m^O1i3)u_`"
    "%)zf&DT-"
    "f^7)wh!J;+E|Z&&()S5l+~bW?7tx`r4;Eb;@d^h4}T3M1SVG;3|eNh29$M)LH{!nXsL%JpubzfQzcPSVB5q5!YA!uxxy"
    "`Tk{yRLY%*B9GQ}dx=yuf?g1uX2Di&%R&T&o$7(0e_5wvcKK<Jj?97oo|&@qhL)xe85-"
    "0rrVPDq%+L@DvqngxHk0!VS;y$(}$+$5zk;x48FT<J_`rNu{`Rr_A+LutB&J8n0KZ4!v6#YOmczMgrWi*1@KEYO9b8XU"
    "<ar(zUeM#<`Xp`>bht#_~}Emn-"
    "+8TqhjsT9_)w5z_K!w4$K{D_GMvD%S5q{z@3lCq`1V1h;dQbbZYShZ5J&75+ArJ(YsU|v(Kle*Zg(6v?OY{*DwWy-tjI"
    "AvTF)o}n}5lRbjn`5q;NVW3PG|=Zr*64hWMjTDwPWTIi`O&?<mpn?~=Uy^)5&?<`kn&B3Irun%NF4cI;ID(Efk;6rpfb"
    "M0Um4|C`M#aDC=p<@{U*&*wX#FIiX#dSg?;S{ii$A6tX9OSmMh7pQ980HH}wbh(J9HZ!qQo#B+qOSosz=4sS`hW&hNE1"
    "V&6nYGnlb|KiWAhUft=&S2s`pu92TVAiHLkl5GT4LS5EeyKCxbVSkU)5yFj$*SA?%<6PN3eX_y*+UcbNF)RQYB+i1w9R"
    "Tt_3TRZ&9HTuuVarr9><NQCRq3u(nazZ`@-"
    ">nt=C6>2N`Xnm$?G`jP?`6`5A0fGKwqd_9rF?VoD7#*?YeH)#ruaH_Yd|JArk)i80KZB`v=rh97?yDrsq<XaPUV({Ae_"
    "y|7Wd#8A_cX!e&gVk*Xf%mZVIgkbrMtc7^smy)Fcs3(a*??y5<t=89=ic>NovMhGJw`zal)DzdJjkw-"
    "1?3F~@P5?<+4;?>RK6~&R*V{~~nzDG06;#F5{@EqTBPX0OmF0cI@-!mRpv6tL~5(dWNA+Km~QAMMAj&$v~mJE(_l|;-"
    "03vg07f)Zcm>~vChJjSTQ+!jG<i}A?8HQ5|}7K|`0ir0;$jhVfHQ(mkgx8g>J?917=GwVW!4$ip)l~!y{vZ^8xzK`qbs"
    "DGbD1erkh*N#9{<xw7-92#>RC}tv}z*MQI4-"
    "6ZD;WvKFC^H||mvfnzP{ChDwwy)B8hpSbNZRF4QYgj2x!yQM50jMB71;PUgpz$_7Xx!EX55Ur%;r#vxk0h_+v7{Xr%e4"
    "-aZ`mxDz+B{XW6aF@4u*?{=gv{`$0f5Re#?bjWo)S2<5$@HLIX<tJTV<EBm7$%-"
    "Y$^5)HSzmg0^I>sAYcU)C$3e!7!&iJh`IwTvCFq{`yQhsvy;vpTlj;gl=|^T9J(ZG5UOLvP4+w>TnKpUzB~)!bRk)$NQ"
    "PR5z7Z4*L5g_ku<j3UeXSVC1ZJJEXttz0jZ?)Sr~Br43&V)TF*tWzNVc4Vv*R!aGpDcs5VCX&<~=v1^+|eH*@_Bix#es"
    "E6mNA7)ThipU0Gw{PLC87k{n2Xx$)*pp?FTMUwn21N$oAgub?6_1hjohsLABep)jqx%>YH&5Ms*WZTGo`)*EuumzReiK"
    "xo*SwE#uNzDIM1S369m4WHo=yU2tFI%flx{dxo2-"
    "T=s%$jKCT<GR5_Q!`${EqkC?YO(b#|`;;@YE!M!k^R`x<VxrCzepIU{#Mtdg>p!nx@Vx4~QsS#gGx!#G5#GWqUqvjhwq"
    "CP6d7vV})=eei6N@%-|`0UA|MQ#Z?M@}Q@Cy&BQIpKbXrMdxCoFGAGNjY5;wXh>2P&6|^(;h{Wn(Y!rr)E~v2h?0~L-"
    "(+u#<}FH{X&0-"
    "4lH9G=;e%zNn`Tx%Te)e=`wH7WYU`!!jAn4ek$Sc#$(wx&cn~s_jl|zOE2Hk@J|3xyDt1n3tj@NW!~jvC+=GH73Q1yQ9"
    "`_r-Qh`riBW)Z>piSTeHBoX8r=spRNl1)XZ*+A02|sdXQ@T(V({b|uK?Oy0V!|oD(xtb4OHfGpV;PIVY7ld+zDsqFnr0"
    "#sw{+PI$IMKTsUGXq7gXSHDCA#Cn6H&VD6DcLDt)w6M1=r#gY%tNDjV*~$jQj&87n<X4Nux@za@FMKci9F992j8%}qZJ"
    "m)a~xTjKFD&T9ROCi>=Zg^aYu1zn)}-Bm9aHkFzWakwYP=7cjFIk--N_92N{wrmBv0yKn>djMQ@qOsCD@*G`~1#rkbg%"
    "x+wL_np?zZHDfEl2KS9Dy9_)7Mg5)!W-"
    "?;q&NyVi+Ux>L6KViInsZhPIkaRFz~jj<#+Dq8m8RjLVe3P<D|eh!i);%J>4R)x%bCz&gb$$C3E~-"
    "5Z&#<M(bw>3sHi>Z&Qw<Xbko8F?5VAy-"
    "+L8fCPUTi+)!_A6JAWKpdp&NDctpMf9|6Avq)q*8W}v=v;#?bc*uB}|pkqKyK_4A~oEKoH#SnR&=)!)@u)HP^6Bx`~)U"
    "yTO^*zy%E%qN1Te!fZ!;s&Ip7*~EhkNkx47f|~A=z4$lDd?hk{F8B<k+!4%7C)1xA!H~L31?Kln*gj~z#qsVEXiUHOHC"
    "JOeOU57SJ87?_+D}I%5GyLKlNV5Fy~Qc0{uYW-!E_Zpv|l9l)5(9c(q-"
    "z`AtSv9uG_2(Z2+@C`9E_nQU=a6Iu)UjyCCs=H_><Jtv>tR#H&3Kd}$!uj9TrLj^w2uYJ|ZR2d8s9;{qWnTqAdI^TtMM"
    "XRhmS4&{vI9jdGvT5&{v(|0Ac2g0`7H6d%U9W1tc(1@)^b}b#8wG|Jlhy<({Zv*9?+A8mjSH!L^Ni8ulpW?YMX~!yLOm"
    "#}>zH-v9go|g370y8y)!KU`!YA_z*&DKc^#${w@!nZIqNbP81_|hi$l4~B^GB0cKADn)?RPTC`C~n|w8YO;gv&B-"
    "cbTAk0%``fwcSdTG=EX;)*Ez7Ym1=ff2y*3NV;3toxiBwdvLDB!-4r@U2{&QyY;C-DcXv)wp)m-"
    "8jM`LsvOT(Hv=od6xQfjf4F9xljU*F=5yw8RZ8I8Gq0;v9p-8e3)!AOgn3_=+y=e>2kFmA=T$QR00"
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
