from __future__ import annotations

import base64
import gzip
import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

_SOURCE_SHA256 = "c71d4ecebd9ddf45ee2cb48411a80484270fe13c33ea6bd8dd82939fedcae316"
_PAYLOAD = (
    "ABzY8000000{^u<?{nKWvfuSr@YD|_8%dSqIBhjm=edpAW-hfej(d0S^fWx0ge<lcsSuQHHO>G2b{7B%fS|18?mB"
    "m|2<$Evi^cu`mRy&`)(gY+zS@^8483%_E6U1?^1P^`DlKx}>#4T#ZWooDspn0^H(7eC9)IISu6}Q$YSUXI=_IP6I"
    "Ey%ET+yzZ1jG(tfsE>XQ=?XgU7Fvi_KW;bbCU13yMq^TFW;%AU6d!#0RP)1J%N9>tHO8tD6dAv?~jVinpN>8gobd"
    "F@~S8gVGNiV;{)%ZOe;oRJdbvKQ&hd)j~BnZdi}rQtC!x~>&MZaN7=A=$cMW!joI+N$o5+{%vh8Rv*>OZ@xyk@s`"
    "4-_b~xHTPpiXlvKih_`n{Wr>z@`kZ-J2Ce|_`A@YlC5Z~6nT|MKdmg?I>hZvp5AAa=><Cfzb#McbX<pN^+z!}0Us"
    "cycoy&**>u1mMNxOBd+*a55d9O>U-V8t6aXEPl9IybQ0e{*D|>pNEs@&wDr57q2cuL1!`!zaEc!S66RC#f8=+V5V"
    "o`S1-oBUoWp07cW(tAa!y1!_QaOfVy}?jlJ(L-Y#Chx?F^>7neWX{0xm>O~<|K#Se?io2G5@;%ndnD20Ii>YrDah"
    "#XE}kXM&KUS0okar5fxGJJjUlOTHa>&*{WzbpXw*K0A4-j9m~%<5O5aC7|%#~zQy<4N!PtE-#0Fuyn9_2TWtFK=E"
    "i5dJ(I!-Sf??_Xd2@K<C_YkRv`(7eXs^aTpwEF3=vzW=tke!B=SZmwP<+YE$UH(oc5<6f`#KedAUpof33e122zS<"
    "s^<@9$}z6c4|EmZUMC^*s2G?^slBqdd%6HS^Y45mjb;l-x7ect&4V>{ttd8XeF87gnr{(~N~|y=Jk2CJ~N6WW@t3"
    "!?@Vz(46L?alhM{jZaPes@W7`;!z%Nin5`&W)Yepi*pC7dQ-x(=)e+N7OL68==Bn|_Cmgirspqwv^_I2Ie|C)&f`"
    "@n7%Lg@kt+)~(x68rZ1(W>P%-WY!Dz!Clk^UDpC2gF!i=Cb)W{FK`zYH37huL{sLLW}Vl1KxhLwS#+WwxTr7s>h$"
    "!_4WM=(@imZT_a6fsW49xI<3@jo1Olz?^QK8*+1IY+}D@i<NAKSmjcHqbzzKc5af4(k#A&JJR%z<cKP|1a+kYI-b"
    ">iv*1DyuYv3!>?tJHC2?7ElF#74{5at^JvS24DlC^B?a3L^vURJQ*+efq~?J~YX(YKmVU<8paJ=A1fHNQqr<=})4"
    "Pq)M7)tA2<FnYhgc(?{=vMz%mspYDoU;ETkmXE3#E)w&b+^&d>3U|lztzF2X#Yt3Buj&EADOg96jVc^BDM`3~1$d"
    ")y6B<UR1$D1ijU!WUL=3M!?}Brzu~jutOM4Cm2Op<_E}(-A$~@{!iiUmU)6w!vP7#he3Fih~WcoP6ibjFnY!4s{4"
    "~=vnzO7rSRiEDpRlqiWyQ~Fsb#JNF^@Vn%I&H8!X2IZ?ZB3h=E5VBO-IMbev+5mVhWJl|z3Yg1--IfA4Fs+|WTW9"
    "f}jecoXGdE86|wyh~w2#WTwj`D80>$@mUpG8V!fh6sd%jDT2FB4MA%;8sas+e`*t0udCO1D!zU0=efQ1u%fE?Vnm"
    "qCcDelm_v~IK+U$*y^=P9Hb0IcM-)^$hU_9H$9jSzeMq%n?a2-u?5HIznQ(zAT1N0sAtU|xuP$q~-(_q`i#zc2KP"
    "$1;>!N&!$^<3m&^XDJEt`SYXn`(}kb@lpBZ>>4giVkrVQ;3CX0@EnhLaWSx81=v)JDU%R^v1>Qo<dxu@s>mZD1>9"
    "yJOP)1S9KP1OjAi(AEzr+=1e2;6=CGS4=)r{k5Bc9rk+&Caa9@q+Q`H$I?6+Q3OQjZ&{f#>63XdLSjBld{ZRzz9b"
    "4xuqr~zY<#hCNf#PFCxb!14w7_FSL~~}*s^23PI9B|K66r%ZZNPWD@g|pCl%&eWde>d2`S|KWS%4*kW6%Ij~+&`B"
    "UVk)asf8{DL1AQt=*SF;YqKh&ryWcAisC}6f94t(^BL9fhnGR0PU-p-Lhu&0`Q$*>YN(0BntAOMWLQAQqX2)Xt!%"
    "jAp1o#M6;gI1aZ6!{<&){HFKpeaPwPQESV<kD}9Y91qaHCF!*d(kuSZo(O9mTOeCH{n_6gUu2Rz9&YSTEb?bNYhP"
    ";~aRwQ3;t)(<VZ>SRpOCF9yj>aE|0nyO8C2MeRP-)Ddo)XSmd!M)r25o4`s|!PR=~ya-oFCcJt)cW3^EhIA#C94w"
    "H#HRimL$Cu+HJj+M7s(!V(zTfA}E0zL{(3lu$Js%@Z{6;i0`+)4y9$k1VzsVRAA~`2%$>lOWm893r`A#{oqVNfgn"
    "j-8AkhkJ#1gsjQ-4%^hSE~zyU3%>%x#-I+oH59bC1w;2fm&b`8G0{u)xdQ^RyGwubEn&?soDs-bDE8mzXq8m!hTU"
    "_aCgT--xy8s26_{Cg-!-U3)6H?+&nG>02@qr=|FfU!{!JxrtobxyI5VPL=$%G}jD?>gr9(wy(t>oiUw4ED4`Os}}"
    "*th^T|!WbNRV$MUFGo~fcc9%heN}KXKk(xj#krdkzh$-4<RS50AdDJH0lQMdc$qd`>s)O%44)6xv^FU=aGB`rqZS"
    ")w57<4XXJhW#_V8kg04Q2_$Ac9iGn5CIdNMG7WGVoZhIjhV(%K~gAS|}cz5XAbPjZsfVOG}A)90H^>0xIkd6u^h%"
    "wwW2_bI9l1m_|_3X!1dk2J+=>K&LP(z?G9&;`6|ptsnwrd=r7O9!`Sg4C$_FO2~Pr+~-^=@6t%MYB<nf6b%??cfV"
    "9-fKm3=3CEZC?+UrE+ws4~kLg?u>ajI@{3LkW9SM}S2Rm`BlMvgZ22H3Sw5pDDND>1KO{eGJJ|9y)9|tG60cmo+I"
    "q%C;PT{ha<5h6P6?9=uOe|&gyTGRo@Fzw%Qz*3oO`<eAgcaDM91W>B7v?@$y)5OZU3FHRmb?Nh4CaPaOoAHQx#q?"
    "<Zx)_;_MHOkDh#5vy9+H*bPx2!yag^7XW2w11X@3$Igr@3L2wcuc=d(MKp#ch<!eRhnP=XGz*NA}*Z737QsUi}Y@"
    "I$T%@hKPvw}NZ(z|^D{D@@R;hUNR`x6f_<j{C7Fju?}?S*I<lB@zOJuYWD0X$gHk0feXo#_q~dFCN@+<Kp7J~~W&"
    "%s?bGQSNXt=81<z#Ng%_6?N`1nXLqgBwepDRLzPzlNHyfZZvanfp;5m2ELfpUa^+@H<PIeVXe#Ln={F23;{qJfAY"
    ";#@3*k0=LYf9j(Yf@<J_@nH|OJM2R_Ur9^~#nHoPv3R%>f$vIUZZVa?(|`z1Qn-i-1nJNyBGYgFE`%3qfeZoFMGd"
    "Kp#GkNDJ?9MJ7WE>HrzzA&zNkA!*aK6~6jcnopSdjsc#R~G1kkj3;KyPE+%m{%3lIKr!>#}Qp|a37dXBG`z+#L+G"
    "Cz$0U}F4?<zf3oQZM^EE<u`gqWclj*yk^**`JkyUiUbSH!dyHZn8E+OnFn``%nI`o?Jsr=WLN5E@gz(a+ze(>l_!"
    "s;R{-HgFKjc!A-Jp&l2aCMzuk;y0$mA=k!6@Z?f6LVhjbfyb^V6r3a&HSXu%e-6b)B*-;c@~wa0Gb<hFmzp@*`)l"
    "S~cf~O>EVeAWcafmrZhT?Y>Dh;kgP#B+!!|j^8xV={g5<kO+e;H<Wd+Lj4>wswz9wXKAKx2^lY&Wf?^rX9A&ZNq0"
    "{DN&keaF91-=B9{WSyXI$CLJE_xawvyks7fN}2f^1jB$5|ej8(@OZSB7rc(F>y5OlBA;F*hh1l{e?#9sYWSN0_K("
    "=O~Ie3veOK#E?5erUYAf<n1ODmP8>B%Xpqt-b(9TdwN#P+jlPt&XS>(Jv){O$JF7cIZKi)k@YUe4uk1y|32}@+7a"
    "b4j1Nf$)~vGQ(W_t?pf|LW2~XgAcm9RP^==JnUMjB4R^sgEAd!BZo1n0@1nHy=(NNWTA(boWI$tbXwFIwZqy2$GP"
    "Lx%M+bH-;<LFo?X?!6aoJ&gN7M*SD$>!5!_G+KShR60;Bf~%jbU%rUPT!V>q^}JRmR<+k}F&?na17IzL68W!geyb"
    "@=sqOD`)pl5ssd!n_8#)O|o@<O<>q?UlrM0uMC4sUT?w*GK=mpjVAiTq69zXsX9YXt(mt56KSY-m%)QJztt`!99R"
    "owm_*nclV)!;$3m?Lw}vs3&4GGu7ELxZQMxNVRsWHk%~jOhhS?+2XorHem(FIh{y_@}4nnRQR`s0+r<fll9GRA;x"
    "w;>0FH<Kw&V1oh8EQ=Nzrm5YW&RCrly!cZ7t{TM2A=hFKE=s^=GImiquQ;Lug_N|TM*_|X^v$)+I<x0UlZ*u>%*1"
    "l^A+B%+C3|Dw4*WnYnGkbms0gbrojMSJ*Bzd9&gs1>fmg;2M!#nt<^ua&QG0FbB{nrB~MMSJ?f`T_!$+8G%US%iY"
    "3>?rJ5j`xr!!b8(zpsL$+7F-SwngB+9X+a1VIy9`GX<12-=W`IosqN4$j4_-Q)zg4q-HtzOEWMYoX3e##bZf>R@M"
    "A4NNubz+K2i{t&4qZ9&~+os;~P;+I@TL5_9E$@h1XZqR>p0{o<9s5lZ(prLUctzNHHW73^@0lK#?w`u&;4dMI-i}"
    "lUhECXkagrh0l_PzV*EJ?3Z2TxH&7QX?sg94LW^NjbqTcyQR6BXK0X~ZQu1H1bVwI9mwM0|-pmXAc)}}YGS(ez4*"
    "rqw8ETVP{s9>=H%mui6w{NPps7~3eLrUM3#|vu4qp!|oNrbC&dajc4b&(}1$u<unwLDuL<<Mmj-2*8UaUak?ifBJ"
    "eLOMMhh~Fah1K~3|c#5#Zna&ZXlNV#-W&|4oS?4&PXt4*;5lOE`@);qRK)BE-OHzgIrKf7Lh7v>>Ld}JZ{<a=)Wm"
    "5mBJ=^f(QnZ@pNjvvMS|7E4PoybT+t6}N7K3^g1A_;{hv|fxdK2$EvskY~*OVu56EV4UyPfwf)7?j4yu56bwGBhM"
    "p@1BjF9E?|A$yFoJ;%e&S*<w^P(uR&l+NYqMF?CRXyrQY>31SEwL1<(r-%ArdngF2F|aR15&fKs4%A_;%O>=+c-%"
    "n59Myq<H?&w*<?0d~?14^MMPL{Yq<@{&I7h7X9T*(cUhRq<Lf3S=--fOQG1>yGGMr4u+C8{_%!D}3vqOlAyf28HJ"
    "TKI5((UsZEJU&s_!|0KJT24SP<!SX@1}i0vYlYk)|AIV3vT~guGOUK4AjM`dzveZZ~G#c_1Rdv^-c`e^Id()s(Q("
    "5>Lpi1;oJeEm0AfHjjvh{WIk8yxzbzUQQ+&<5uJ?K1rgnVrYY)#FzC2AHjC35cH5<Iog=yH+`5O<_J*++U~IfU5i"
    "i;hHd%e~3}#=$8;RxiP3=H)af>g*RU4p%8x-x+QZq&?jjrxZ#C|z5CTHU-yYvJNn<2xb09&SsNyU948Ymjn?4^6I"
    "7rGEBAPdXlcF(Jvag>>i(VkMU7Ff56)u2a|%!GNG)=B!LfKSyZk<m3tUw>w0d4Qq8Qyp6=3>Uq~*lWB;yPV0s<&k"
    "FAVHZW^jOggAOrI~uE4|h;a)AsdI?U5nUDpI<`ILbZTcT|f9rhD!A-dP*$=IeKCe3;orNY!1*!swlE_m6kV`#e=p"
    "tUD!<8T=OaF+=|ZIZi76vTeqW_OWPI(L-p(>B0Z@)BRe4clDvO;j@5794T3Qk?<AJPOxPz;{w);J!m~dFo>usTt7"
    "NPZ|mZC(uuSbyE0Ug+!Wi>a=ZjU11l+RCA!pOvIm=M~PgquXg(il&I9+;1z{kdL7EZDngORt8ua2QvCK_-~6x?DR"
    "L$T(s;g&P(c03&wagYP{z=rW~8Tw&CrTjpSIHJHbvOUcx*07xQp&cOlL+Ywu|;0-y4JVCp{mJCR44uO1BIIfM~VB"
    "`=DN4+(zYrYG6A)8sUHOg_yof)<I@z4D0X_IC7K_Uw6g;wEYzdUxMfh1u?NKFX_WiA!KZmpsJig-4hv$lNaEUGAd"
    "h*`Mp%$ILb%?34H`+CBj$vmo~6`VY^9qA&9MK{WO}s?V<;<U=0H>vFI)@z@WxXUK*5B*=S?vh7Xn6IeocOs;;S_E"
    "IR^SP2|mqlJ&A%zAN<}cLQtlu(In}tkc+aztJ&K+A@^oMdp<t8O!%VFI3?cHldcG{WP?$HX6;~_N)DZf~=xxZS``"
    "$Wn{uzyS)_Y4?0&%xPfE)+w!NB8(jM+<;5DMTKPfCI=GSW?Nc|FtilR0Kq+D7+^K7AC|z~xMc`oOA>U+)lZXRsWr"
    "Rp|0WiwxD5);km0{_G{cB^39v#-bK|jI*IJfc<GDo*!Ehyoq(1la{uC&?_JX*^>kjmM-&<$!(!XJ$2e1?Ty;A&@<"
    "3p2m^fp?{JD%ddgnfFHf(ob^(U)Pg*jm`2VKYRBR-L2`r|Mjnb;pZ*1rgeWEZPV;vAI*606}!vN1q2v~&sQG|RM0"
    "6b-`oI09jF2#L<k!hWtL*8=9gGN=|Zj{M05rOzSMem5t=Q0w-NDc5R*YN1>D0J1&baX3<`))Lf{xvg9OA+xLilXB"
    "O%POQPf?laI<0hia}(6X`t9x31kXIe%Ka!;Cg=x3h7<_^&j5bH&-{fv{KQ$BF_#Zo#tiXu}2o~tLQdks7)ZYJMh-"
    "{eGl;8Su&94U=Stk=vy#XS8wH8WzZGj%c4}^F`$o*;G4ztsE_dwaSUM5)MDB0sB3<oeFn*vNTr6zD88As&nn&p|E"
    "G5&VuwGqTQ@xU{?ogJ)^bz8uM3%QiYIIrZ$vje^4Xv~91ijSGv_}NvbhhCAq==C`JF7y5z-W3U)Jm1SF>6z1)g@v"
    "D{p25#L~*J8aUeP&SPMZN#AIACYiGu*L@JcdpXYMM(POqh<!Bn@^k&H;PcgN^kV&?@1$kJ%LGW`=nyLHI*FW~Ox3"
    "jd_WMXA4=_-MJeH<p`sPt^|02t3efL0($=lL>Fcmg?ka&6d9)NBcemjkMwONt%c`5h)U}YhWfLMfg$kq_JRiZd%o"
    "FnkAEH>$FihK3;KqcYOQWbHLjci2i+3|T0{HW0AHxQ6d6IZY5Zei>Atq&N1-0&t%egAHBQQlF&^M-o-Km!{^NfJh"
    "~-|r8H!U_-33ik(f<+t%ICnuf=^@kAZ+h_xiE@9r(Q5m42*OG+j50a`YWv%Q^%!H4cb_?v3uTW{>Ah(?=#)raHQ*"
    ">+e>-nSxDED(WB{38o`IdN+E;3)}M|N}w%C-$c@Q+4_Ubo;WKMHt?RRZ5{-bt-Rj$Fsc?vz_k;(|6lR|ZWLgc~4I"
    ";2Mk!dYbCinC&WWL4VNSfZKq!ndf~5iO0KW=6(NqfuF}~Q+3FeJ{RT!6|&P=?Z2n`d>AVjh4iJbF#IqBSN#}+b*k"
    "S-c8?@>zkIWTQ-MD|N|75EyhoSBxh$G`X$(7GyQu-ph500*I&|%Hc|Fa4`>xVF5E5T{a|4-d(E+KG&kl5D@U>$|d"
    "at+zE%%WX=AqK=x4xLt2xYIh9tf@jT4w3=@r6k-`Q~Ix?Bf_$gVgkhR*4S+5q==<+px98kt$D8Fa9_QHfp8f(m5U"
    ";{>A`8d>J$>9%KnxsC|CQeE%%8iBC2mejSt)EyMRa<;0xBiO!E1F3m*>40?-owvg5`b4bqqLlZkPk{C)xZ|3nqo#"
    "3F-s*kPe$8${<gPMwtOKZ{qt&9Z^`i#`Lov~OTF-HG%47Fw~yxs8-v^so<@Z|j5xC+rK;vgB{=Sc_~VW-gOXwra}"
    "OAY~2THq|q&1)Whx(_YP!_XrzbT)u@r$WaOUVp#Of_9z7$}?*5Y83WD4rF&j;{7`j?_+Xg_o}-b=wDjJJ1cuibk~"
    "H(_4>6AX6;dmgLl3IWZd@%DN^_t76mTAvi^)MC0nkc_c?vZlRkIxs8FcBsQJ9DhV#L=F_7$83z;w;gCfYYi+1TEW"
    "uG)rkH-bR07%oT-y7oIbUOap1M|9pfV0{}Ih8Ke(KE)o@_n|pkLWK5mOim4i=nF_RY41z2e{McKYQ9P^<+T`dNc^"
    "s3mo+U&m0}Z_jz;=ykdqs@@_UMMdOhdZ^|MsvI4??`jTQycPnH>BP}yfn@_%vGcpITb+~pgWbs4w4o}OeeQ0kn%V"
    "guFlCz_YDO_KJAfELv(3noL?KWF98*1E89+A4vlw;G4o#~kB1J%04I5Taz;rE^Uu<fAxVxu@Z@MS=E&n=km4eot+"
    "ca(v#<Y88H4T+goaZgsoH7=OXq>MUn@qP!tkCA{Yazn7>jtSFubQm!348Lg*9w5usDi};qUAIVgip(M581^t8P=a"
    "2DB1!EEzR+`{&v_D#PJUp$vncL_$(Z;wU%2n4!w)&^=PHduVXQ+uh3$X^zlWZhOh*SuTo#<;B^qvUaFLv4;&%r;8"
    "c1-UWyp6ZVcrE+fYIL+v2<791u`%bLT8<`s*U_pa-?H5bQ}r!jeP|c7SFJ|L`vm3CqV0pA;TpAlE3t0Y8CF#6$`$"
    "fVBFoQ-VuJWxi52Ij4IsV*NZn-5F2b00jhsv+8Ae04;$DtjZZAQPsan-XO`{TAY;6Cw>Baksz5-i(i?hjI}GuNB@"
    "FvB`ED+rxAguW>?8L-g<t>x"
)


def main() -> None:
    source = gzip.decompress(base64.b85decode(_PAYLOAD.encode("ascii")))
    if hashlib.sha256(source).hexdigest() != _SOURCE_SHA256:
        raise RuntimeError("embedded deterministic experiment source hash mismatch")
    with tempfile.TemporaryDirectory(prefix="price-volume-lead-lag-") as name:
        script = Path(name) / "experiment.py"
        script.write_bytes(source)
        sys.argv[0] = str(script)
        runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
