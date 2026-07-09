import React from "react";
import Svg, {
  Circle,
  Defs,
  Ellipse,
  G,
  LinearGradient,
  RadialGradient,
  Stop,
  Path,
  Rect,
  ClipPath,
} from "react-native-svg";

type StroopwafelTokenProps = {
  size?: number;
};

export function StroopwafelToken({ size = 128 }: StroopwafelTokenProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 256 256" fill="none">
      <Defs>
        <RadialGradient id="waffleBase" cx="50%" cy="38%" r="62%">
          <Stop offset="0%" stopColor="#FFD179" />
          <Stop offset="38%" stopColor="#F3A535" />
          <Stop offset="72%" stopColor="#D97812" />
          <Stop offset="100%" stopColor="#9B4306" />
        </RadialGradient>

        <RadialGradient id="waffleTop" cx="45%" cy="30%" r="68%">
          <Stop offset="0%" stopColor="#FFE3A3" />
          <Stop offset="36%" stopColor="#F8B84C" />
          <Stop offset="74%" stopColor="#D87512" />
          <Stop offset="100%" stopColor="#8A3704" />
        </RadialGradient>

        <LinearGradient id="caramel" x1="36" y1="154" x2="220" y2="206">
          <Stop offset="0%" stopColor="#FFB24A" />
          <Stop offset="34%" stopColor="#D56A09" />
          <Stop offset="62%" stopColor="#A84300" />
          <Stop offset="100%" stopColor="#FF9E34" />
        </LinearGradient>

        <LinearGradient id="gridLight" x1="40" y1="30" x2="220" y2="220">
          <Stop offset="0%" stopColor="#FFE7A9" />
          <Stop offset="45%" stopColor="#F6B94F" />
          <Stop offset="100%" stopColor="#A94706" />
        </LinearGradient>

        <LinearGradient id="gridDark" x1="32" y1="32" x2="224" y2="224">
          <Stop offset="0%" stopColor="#B85608" />
          <Stop offset="50%" stopColor="#873204" />
          <Stop offset="100%" stopColor="#F2A33C" />
        </LinearGradient>

        <RadialGradient id="centerStamp" cx="48%" cy="36%" r="70%">
          <Stop offset="0%" stopColor="#F8BE5A" />
          <Stop offset="62%" stopColor="#D07110" />
          <Stop offset="100%" stopColor="#8F3904" />
        </RadialGradient>

        <ClipPath id="coinClip">
          <Circle cx="128" cy="118" r="92" />
        </ClipPath>
      </Defs>

      {/* soft shadow */}
      <Ellipse cx="128" cy="220" rx="78" ry="20" fill="#5B2500" opacity="0.24" />

      {/* caramel layer behind */}
      <Path
        d="M38 138C39 181 79 216 128 216C177 216 217 181 218 138C210 158 176 176 128 176C80 176 46 158 38 138Z"
        fill="url(#caramel)"
      />

      {/* caramel glossy drops */}
      <Path
        d="M50 162C66 178 88 187 111 187C117 187 121 192 118 197C114 205 96 202 78 194C61 187 49 175 45 166C43 161 46 158 50 162Z"
        fill="#FFB45A"
        opacity="0.85"
      />
      <Path
        d="M153 188C181 184 201 171 211 156C214 151 220 154 218 160C214 178 188 199 157 202C148 203 146 190 153 188Z"
        fill="#FFBA61"
        opacity="0.75"
      />

      {/* lower waffle edge */}
      <Circle cx="128" cy="132" r="94" fill="url(#waffleBase)" />
      <Circle cx="128" cy="132" r="88" fill="none" stroke="#7A2F05" strokeWidth="4" opacity="0.35" />

      {/* top waffle */}
      <Circle cx="128" cy="118" r="94" fill="url(#waffleTop)" />
      <Circle cx="128" cy="118" r="94" fill="none" stroke="#FFE0A1" strokeWidth="3" opacity="0.75" />
      <Circle cx="128" cy="118" r="88" fill="none" stroke="#A94905" strokeWidth="2" opacity="0.55" />

      {/* waffle grid clipped inside circle */}
      <G clipPath="url(#coinClip)" opacity="0.95">
        {/* dark grooves diagonal 1 */}
        {[-120, -92, -64, -36, -8, 20, 48, 76, 104, 132, 160, 188, 216].map((x, i) => (
          <Rect
            key={`d1-${i}`}
            x={x}
            y="-20"
            width="9"
            height="330"
            rx="4.5"
            transform={`rotate(45 ${x} 0)`}
            fill="url(#gridDark)"
            opacity="0.72"
          />
        ))}

        {/* light ridge diagonal 1 */}
        {[-105, -77, -49, -21, 7, 35, 63, 91, 119, 147, 175, 203, 231].map((x, i) => (
          <Rect
            key={`l1-${i}`}
            x={x}
            y="-20"
            width="4"
            height="330"
            rx="2"
            transform={`rotate(45 ${x} 0)`}
            fill="url(#gridLight)"
            opacity="0.52"
          />
        ))}

        {/* dark grooves diagonal 2 */}
        {[-80, -52, -24, 4, 32, 60, 88, 116, 144, 172, 200, 228, 256, 284].map((x, i) => (
          <Rect
            key={`d2-${i}`}
            x={x}
            y="-40"
            width="9"
            height="340"
            rx="4.5"
            transform={`rotate(-45 ${x} 0)`}
            fill="url(#gridDark)"
            opacity="0.67"
          />
        ))}

        {/* light ridge diagonal 2 */}
        {[-66, -38, -10, 18, 46, 74, 102, 130, 158, 186, 214, 242, 270].map((x, i) => (
          <Rect
            key={`l2-${i}`}
            x={x}
            y="-40"
            width="4"
            height="340"
            rx="2"
            transform={`rotate(-45 ${x} 0)`}
            fill="url(#gridLight)"
            opacity="0.48"
          />
        ))}
      </G>

      {/* toasted spots */}
      <Circle cx="66" cy="92" r="7" fill="#9C3E04" opacity="0.18" />
      <Circle cx="88" cy="171" r="8" fill="#7C2F03" opacity="0.16" />
      <Circle cx="190" cy="100" r="9" fill="#8A3403" opacity="0.14" />
      <Circle cx="174" cy="164" r="6" fill="#7B2E03" opacity="0.16" />
      <Circle cx="113" cy="63" r="5" fill="#FFFFFF" opacity="0.18" />

      {/* center stamp */}
      <Circle cx="128" cy="118" r="46" fill="url(#centerStamp)" opacity="0.96" />
      <Circle cx="128" cy="118" r="42" fill="none" stroke="#7A2B03" strokeWidth="3" opacity="0.55" />
      <Circle cx="128" cy="118" r="36" fill="none" stroke="#FFD27C" strokeWidth="2" opacity="0.38" />

      {/* windmill emboss */}
      <G
        stroke="#713000"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.82"
      >
        <Path d="M128 98V142" />
        <Path d="M108 142H148" />
        <Path d="M113 142L118 122H138L143 142" />
        <Path d="M118 122L128 112L138 122" />
        <Path d="M128 112L100 84" />
        <Path d="M128 112L156 84" />
        <Path d="M128 112L100 140" />
        <Path d="M128 112L156 140" />
        <Path d="M100 84L92 76" />
        <Path d="M156 84L164 76" />
        <Path d="M100 140L92 148" />
        <Path d="M156 140L164 148" />
      </G>

      {/* windmill highlights */}
      <G
        stroke="#FFD58A"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      >
        <Path d="M128 99V139" />
        <Path d="M116 142H144" />
        <Path d="M128 112L102 86" />
        <Path d="M128 112L154 86" />
        <Path d="M128 112L102 138" />
        <Path d="M128 112L154 138" />
      </G>

      {/* outer edge highlights */}
      <Path
        d="M56 66C78 42 113 30 148 36C181 42 207 64 217 94"
        stroke="#FFE2A1"
        strokeWidth="5"
        strokeLinecap="round"
        opacity="0.56"
      />
      <Path
        d="M44 149C58 194 111 218 160 204C184 197 204 181 215 160"
        stroke="#6F2A03"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.35"
      />
      <Path
        d="M48 156C65 195 110 213 153 205C180 200 203 184 215 160"
        stroke="#FFC06A"
        strokeWidth="3"
        strokeLinecap="round"
        opacity="0.4"
      />
    </Svg>
  );
}
