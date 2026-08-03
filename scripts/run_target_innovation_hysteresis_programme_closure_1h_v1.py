from __future__ import annotations

# ruff: noqa: E501
# fmt: off

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY = "causal-target-innovation-hysteresis-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_target_innovation_hysteresis_mechanisms_1h_v1"
_PAYLOAD = (
    "ABzY8Zt-tw0{`t>TW{k=mVVz~K`7Xlj-;^eMbA_3^aL}&T!Kx{V1RVM6v>jsgd#O0Ww(>`f8XyENlBI^x9rWs0y~"
    "|wTP{|es&oHN@#vSCzbgx0=RWQIW?Q-5&u)I1Wv=t-#+CK#W~N-c%Jak&%vsA<mUE$%&J|m!EVHpvD<z~Cb~c~ot"
    "}e;~G}64;)&1-y4r5JS=B`Rt-ly5NOPkuK_wHeKqn7l%a$Q%hFrzOU+V5xIHj6!_C~t5q-}_>*a+|Vxh^7NadDV2"
    "g*3-WD<cqZRUB2__*7fUdcJtlLRlRR(B645WMRVWHqrbd;7ZrY0)+OzRfgC@3SNHhXv{706f9+g_hrR>d7F-l%eL"
    "Ih~uI)=#MXva9*Yz7;_q4RBK$WO$Kyb6$L~D!;lt2{w;zYhDN}aEK-eVm9-!%|(iA^4&=FYd3d!QK`*Z$;tY*2)w"
    "&9N5h$o;U_7JG$*VEwk~`o+4*qg6=^Vi?P7e+!~_K3d@jUp;u&f=|c|q-ag;@1wu{?c2!Zx$nB!_k+wJz4VsUwS^"
    "8Qo$-@rebc*YcEjSw;~m+FtE#l}?#>6L=FPfk`?T5hX}8OW^VAia66(z=nAOTvou8kq>0Nv4Kf5Mt`t?Y@OS6*9w"
    "1q_xH{0G}W?HoFo|G}W>D%4q6@}mWda(Cyx836D=k_3Zrm)6zGQ^aGn`W(dMZf;sYGQHS>{@ILJzu*gG+dH0Q<rs"
    "3wZooG(}hE<c2)Jc)vfP$ZJl;&*KQ$Td?qtXeQ_I@hQ%~3jBiiIe{^||J*zUu3H=7%Q06H)Ss$hi0<9bHaObOLOB"
    "R_91`X><n>L+{FZFPzW>e<fLD17apI|;somaaqxcM*G*5|uGq1!azgzWfcHcH4Bk?W$tI2Pp4i*D<43KLPj21gNu"
    "5h0*NG#_3Th|Xtl^Ksukb=7w5K(X~d;-o|{Z=0@*Mu7zi{TdYdwyAG@*GCzSyCy#zH=Ye=#`9{h_B^;qmkwU!i@g"
    "XBL2k3_Lm*4tuE##*&&RV`AB2kE&XAzPL99WjAhZ|oentiHw+>3&9j~iM?tSYhPMzBn2TR#HE$i*>V0TSh__j+!f"
    "H_Rvx)OuXXSXHm?v5V7YM$GKLK5sepWOKnnf5c<@{Xbjl(TKhvqJ11YUqP(Z-|8{;=en#p0<TVYAk|@(^*L;2<8}"
    "sn%_f}Unt2VY>aS>Sl#V5AoLJ{8OkKxplxyh?25C|bQ!fxhKNp7qk-y@0{=*V_V>;Y)BfxI@4x!P`#(nE@X^NiEv"
    "!7)&@dPFwL?^CdnC>N;ddCNPs522xjpnogkfwr%IyP5IYifd?O=Sxfz2Vy!Tqp%?slE47NZ-KH5@q@*JAz9flc3)"
    "-D2A|x2@Z3{9=sG3$|X|G3>Q2J7k<-m1CYs_h}WnWn@uLLpKSv^&6}>_V-}^PvbHsg3F-i?`Ch`y<PnM+jsA=^*{"
    "gno8ja4pXL)a%4hp5|9NT<_(TnIpQwF0KJ+1X5W)TS_`HwRhh2^W<jCxxqGQ?b_k2Bx{aIg6VlTYclK4b$;QrW)("
    "iZ3^z%hC-%B^yluZGc(UQYcHn8(4;;rX|1SsX#SF;yHg1cLbhn=sg=$P@>dG^G#FtTLDXL=)gBgVn>rI&z&c;Whj"
    "0T{X>5VK(JXvQ=#fAr$~4X;<EE5Ej@{TCT}xR`3K$=vmcdl=T=qXH_VrGm&T@)FLr4%S9m_<GSEN=1GxzR&bMx*)"
    "ahKds9*@;kGC;qnzO~&NJpRCo-0Jw@P%9#aQnO$F*=nq?oKa4Y`7HDGtGv1|iS6Us=txVXV+v<w_@cW@NU~iQu`B"
    "tJo!08X<UL@F-bHlc_{=n;Xqk9+2ZnLWa62k(L#yY7kcdn{e*71#V4;JQsjVcbI`d(2pFZdzib=?nki;DXi*CaOG"
    "Q)vX%<=)Ikrq4_miIHw4}T7(fi_o4l!L99Fu6OC#=)a5~VUY~T+v$(Ss7o`}L488gW<$qVm`V&#N}Vse)_$%K+g5"
    "eu>6ISP!daI2zV22zs6Y)?1DNYo{)@DQ4HN+~0K<}&6JFC^q^a!5aeNKv>rAxvxxv{_(dUr56^Uu7V7-?Tris^&g"
    "zcd$Sa3p_GPSqsJ=VV*<oILbh4q)M_lv+^ufTowX_lFWoId|`0<oLRYo$$2OgglFVf4^;zW-irh!)QX8r@I<Rjvp"
    "k0xBn5}LWrfdq9xJDP4s$hmo?{5hiX_%jGQ)(|WQSV-LmcW~I{+DyzWnsaHbcZk39};eB)M5DaV{v=%nuKKF1Lq6"
    "X~De_27hwros$JqNs-}m?o7eGbdG5jYq*HkMPW=Lh0cA(7~Cf3+Tc+8+Hz0Su_RF}u_zgxD~wlIszqGHHq-E`BvV"
    "i{SdO9dSQbtTYv2tlZ4?vQ5T~QOaenCwk;GoZC`^%Sp{3)wgtIbTtb8Vng$)rZ988kMRKq+L6vp^d12EW48_O7l("
    "mg&*_xO;YP~EM3(7&(B+Ypy=?vijQa1~<a5PeZjDG&?z2Pq$MjG)+*$1w@4#8d`f0PR#WqjVq~^c~GR`imNF0>6l"
    "$fO%9ngR{Hg5Ft{JI2N$Fq&$Li1AnCz_(8Pj)+uK?UK7k6Q^KUMi}{plpWyyH=8}%iB*d)YSjn8m)a+(~L17cbUn"
    "znE5%5^Y>6+2H+V^9DGH|3~D=ZfxA(jvkq|x|?cngvUlb98XF=>^?BrXMG*vKlv7Gsd36Nc<W+QeQ6NUJgwhO--q"
    "5q3IK5x*TBr5Y+1+RhV0LRhU7Gm>;NKAh??xXmX5&rmo)^sx;7ZpfFz&k#-zKaK{^e?0R8%!lZ_Dxp``rDuwoF+("
    "3kZIZ#pyE<e{;KyJzX<jDK$aiuX$4Dx%WK8)*Y~~2-@IYm?jV%WBUfz$_K_v*fal&lENk2wvuAwp(fY>ow8nw()K"
    "<`}#b%%gc*Te@3g}p(;JeXWk&^a~)kmiORbWXqP<kjjur=v^4{td)_#AeXIAi~UbNZJQM#)4Z$LX0hoB{mE7c&Mu"
    ";XD3YC!2!ub@9}%K#mN`Rl6>otdQNFGA&9b&ntWpKqx)+FQiqry{SH?YpH9%~OH`<rI(ec(7|J6R%J@nZswXN`|2"
    "I{bu*A%RQy9))phCMe{4*+qutEf6^0Erqi3<6rOVz?jm_|sBwY3ZYiA`Y|VU-J{xEM&_Ghvz{x=Mh3ZKCJl7c4c%"
    "Yy3D)(*whiPh$)J4%6@_mR!m2Uu_4^MQRQ;C`ujTY^Y}OZyl@8uKn$!HOz(cL>ZxMED)XT+%6N2)M!l-!nL^&t`|"
    "d?q2wiP2na~SB1uewcuh%uL@j_FC<i`b#RUhK3MZf-JrtP0564#l=j=Y%xe!Rz(6py}#!ZL;S|=10Htyrm4K2>ew"
    "UykSh7bvs6O4vCN&<PPOJ`HPiC@=*<_-}Ch%Y(9I7c@I;m-Pqp&Fp?)BFOr0+b{<=*zfO3<>cuw-QN}o#z(t_X)Q"
    "+zm?B$%N}zJu>KoxtN9Xc|59cd2UL5^Yyu-a$7>Svgq`xrv|v=NU#VFXZ^yju)6@%jg&pfe>lZVdETufLW57~<j$"
    "4bGjh}MM8DojQTC*~SyZ-OF6@1B<)(W^zi6fp@<wwl(AH&PA>N494STvJL15GG?;>WOHf#6OS_(TT4<H`c^^Al7@"
    ";z9h6C2B);Bn*V1;g;``{ugX1D0UfCC&vzcbisHk7$ue(Q7=wnAubAt19=KV$I*#=jes<Eu_$>HEA**=0E-3i!8w"
    "-zGpKR|%I&8Dl1Ro{BE5c2K<u%Axa5g|ZHw#VBN41(V+B&UyzDLpd4^e~IR1HseDu=9Ng}vRjCd>^6C<vpt`p~^!"
    "xN(t1Wxq?QNnh#B;av%;DG%zY3PFCI=L_i2Ihc_si4-&t|gZVV{r92QT7#*VJNt?5sdBvlE<P^3@j>Z%~{dFZctk"
    "5Cz%of2}Q7mdtDu6I2Kry7*g$3qKO59c><6n?PbYGPB<)P02;4ysRW==!;B3(iMWXY0753QFEAN$C=NU4D0KOeV8"
    "UC|i_wM_$wVOZF?*$G619{jR#vD)J!3VD>@kTE99}6Kgfw6rl<6lx14>jv#V;}%Lgc99jnW7N&k2V;77n8exEM9&"
    ")h;Cw@eJJ@*vqjPxdsq7W-8XNGaLq&ggXiWji16WSO&6~Iv0zXhTUkovwA8WloCMQh>|Z#RzPMzJVF>Djy-E%mpz"
    "q`)k}+G8$_MNUbY^CSvU`H76GkSNC+^78H7(AUX&b5NI*XLPnok4qD$Wx;rgkBIGoa;<gzcyR`C*=M$HJryi!6)v"
    "|L~xCgRKKO39_6^uQ7B`D+AZU@8)+Tyt@PZ7pIYGGWZmgLwcXX3qp4NECTFri-5I5?1g@$VD0gk=ICu0l&u-6==<"
    "6<B=%EOpK6^DDf)ev6Pu$fAp5&1PTiq${BfHHt-_J)l(?Qlrk3K@LE_L#ECc#Sxa%HY`9q(p<!v3CG4`@h$Ygn)G"
    "(XGzAi2U1k$S!6|+aOVH}#V<Xq?CvPRkhg63yXApA{BL`?mXq=k))<c3PfYox=aU0UQ?L>{j7Wy>LKDZ!d}71CJ%"
    ">cBN9yqWkkr7LNr<ov93l!{}Eu=rFsD3e)YEJgXNlNJZ0gA)hDd6nrTG17^}@fa8E)A#ckhKn+EmJAI<I8w9q6zK"
    "MyV8!$%{pgL(p)(`hczVrUcAJhGaPHV_cqKQ;^NZ;HX;(*dSR3uTI;Jki5A}!o&6|G=hq`(5Ci>yGI@S+Fn!0B~A"
    "6PVqG{PB%u1e~|a&@%t){2I1E#J<gy6K~-_h6iMbo=$8o|;`E*XHZ8$7#XHGWrv(Dt0**O$xxe$W>LeYIg0|eAUg"
    "PY}ZGV#YIOiGe6WTN3Xx5sXZ>*_nn1~oUu1=8NGkp-c{Dr4iw&jjhjSkS48yQEb=SrBU+LyzW5^g8s`|>ZldYdEE"
    ";ajg0zMwzee8#d!!G8)P9Zr8pgj3mWU63aUY|1@9^PmT`v#p{u+Jl>G2=nL|@V9hkCJCVBqBE%@zNAsHdwS3?QQ7"
    "=O1JI_!2olCI3mE=&H=nbPnVpX^3w41U;gg{4gh6-bLB=961)q>7_6eIV~r0f`;e{O@&FQu)~~iI~K@I*BK|LV<5"
    "*yazctgE&(#3p>Rh<j}n|R%nA2T7s!RvabRsel9RCt<ScOL$gGJ6W{n=m(G5=^Hvw6UPC#Zl;({xrTACj&Bm&0)("
    "g%(?_6r*?wGDIV_C!5LlLeY`<T2Fnfo&0wlA!wuInaz%m=i7>PH8^U@i_C#Q2GXHe3^s;g=(H20p<)U2K(#+F*ZF"
    "Pi2*r`#Nt3K6u?2RBmZAgNo!82QCL2R4~ql6P+_UZheO%O2MwEGR8$DsOXPy&m|Z4fB!^7-_;`@L8F=M<BxeQ%Pe"
    "K2jf|-D=j3jj&lmW9GcA)}A4<Z($5m3eP9L?dFeBy{;FB@r!;h2E*LBV2_V!-J9l;)9wX|3WD*Oou>x&VNQoL#bk"
    "4MMaRs0}AkOJyf&2Okbv3XpLy0}<>cV8Byqk2P#Yiy7cZPzhEKha;3Vx~`O?PAt1bkBw&$dZMQTvjQg`oS6J&uoy"
    "Ks2O*6?b|Gek_RPIHLVqyPUX{KosJD}P3nRKfjWSP-m1DbTmp9bBNzL(1T|G=0;P*q?jlz2)8e2p^Jl`n&!%g(&%"
    "{Onq{r1h9F#A=#-GRv0Z~ye?=ZRd|;(aBxGi~%&GV^?M{FU23?a9A#;rZtJ)5S0NzQOZLpZ$8n>C#uX%ReF%O!3{"
    "=S9EOWLmP6r0ZzONUlHk|d*D0zI?F1+vA&61v~PW{o3eYLhkaS^n%&e{zYNiqzN_*;lcukbz)vPW`ihM5cM%-+*;"
    "(+OFcSp7-hcmOw1Q{^YZH>I9_E4G(d*FQtwD+7<arpOe)oqDb<n^98kicPp@H!H@L*8Q@Syl{SByY$^m=R#=(ktZ"
    "ass?q869<%kDc6v6A>^%*EfOMq1zpYTs3WIA>TKAPs$j(!9Ub=sAIP7*I<VF&pY4VjUDHlh)xZY`_}O2uT8Xv%k8"
    "f6^Qd#=QgeV^kKgv4+w*Arrcjd+RX2QD=r%l|FBc6JLNs>Rg4fx<yEp&cz4`yNd-KzO{15HvW4qxv000"
)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_hashed(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.with_name(f"{path.name}.sha256").write_text(f"{digest(payload)}\n")


def run(tested_head: str, output_dir: Path) -> None:
    if len(tested_head) != 40 or any(char not in "0123456789abcdef" for char in tested_head):
        raise ValueError("tested head must be a lowercase 40-character SHA")
    bound = json.loads(gzip.decompress(base64.b85decode(_PAYLOAD)))
    evidence = bound["evidence_template"]
    evidence["tested_head"] = tested_head
    assert evidence["family_id"] == FAMILY
    assert evidence["verdict"] == VERDICT
    assert evidence["closure_gate_pass_count"] == 2
    assert evidence["closure_gate_total"] == 10
    assert evidence["candidate_count"] == 0
    assert evidence["new_market_data_rows"] == 0
    assert evidence["oos_accessed"] is False
    assert set(evidence["target_evidence"]) == {
        "BTC-USDT", "ETH-USDT", "ADA-USDT", "XRP-USDT"
    }
    assert sum(evidence["target_evidence"]["ADA-USDT"]["original_gates"]) == 10
    assert sum(evidence["target_evidence"]["XRP-USDT"]["original_gates"]) == 8

    output_dir.mkdir(parents=True, exist_ok=True)
    write_hashed(output_dir / "evidence.json", canonical_json(evidence))
    write_hashed(
        output_dir / "source-records.json",
        canonical_json(bound["source_records"]),
    )
    write_hashed(output_dir / "report.md", bound["report"].encode())
    manifest = {
        path.name: digest(path.read_bytes())
        for path in sorted(output_dir.iterdir())
        if path.is_file() and not path.name.endswith(".sha256")
    }
    write_hashed(output_dir / "manifest.json", canonical_json(manifest))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    run(args.tested_head, args.output_dir)


if __name__ == "__main__":
    main()
