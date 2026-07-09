import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { StroopwafelToken } from "@/components/StroopwafelToken";

type StroopwafelBalanceProps = {
  amount: number;
};

export function StroopwafelBalance({ amount }: StroopwafelBalanceProps) {
  return (
    <View style={styles.chip}>
      <StroopwafelToken size={34} />
      <Text style={styles.amount}>{amount.toLocaleString("nl-NL")}</Text>
      <View style={styles.plus}>
        <Text style={styles.plusText}>+</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    height: 58,
    paddingLeft: 10,
    paddingRight: 8,
    borderRadius: 999,
    backgroundColor: "rgba(255, 255, 255, 0.88)",
    borderWidth: 1,
    borderColor: "rgba(226, 232, 240, 0.9)",
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    shadowColor: "#0F172A",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.12,
    shadowRadius: 24,
    elevation: 8,
  },
  amount: {
    fontSize: 24,
    fontWeight: "800",
    color: "#3A1D0A",
    letterSpacing: -0.5,
  },
  plus: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#E99435",
    shadowColor: "#8A3A05",
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.22,
    shadowRadius: 10,
    elevation: 6,
  },
  plusText: {
    fontSize: 27,
    lineHeight: 30,
    fontWeight: "700",
    color: "#FFFFFF",
  },
});
