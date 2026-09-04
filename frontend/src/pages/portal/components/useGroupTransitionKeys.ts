/** 权限组展开与收起动画的过渡 key 生命周期。 */

import { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

const TRANSITION_ANIMATION_MS = 160;

type TransitionDirection = "entering" | "exiting";
type SetKeys = Dispatch<SetStateAction<string[]>>;

/**
 * 正在进场 / 退场的权限组 key。
 *
 * 过渡集合必须在渲染期同步推进, 不能等 useEffect: 收起的那一次渲染里 isExpanded 已经是 false,
 * 若 exiting 集合晚一拍才出现, 子行会先被卸载、再带着退场动画重新挂上, 表现为收起时闪一下。
 * 渲染期 setState 会让 React 立刻用新状态重跑本组件, 提交到 DOM 的只有最终结果。
 */
export function useGroupTransitionKeys(
  expandedGroupKeys: string[],
  direction: TransitionDirection,
): string[] {
  const [previousExpandedGroupKeys, setPreviousExpandedGroupKeys] = useState(expandedGroupKeys);
  const [transitionKeys, setTransitionKeys] = useState<string[]>([]);
  const timeoutIdsByKey = useRef(new Map<string, number>());

  if (!stringListsAreEqual(previousExpandedGroupKeys, expandedGroupKeys)) {
    setPreviousExpandedGroupKeys(expandedGroupKeys);
    updateKeys(setTransitionKeys, (current) =>
      nextTransitionKeys(current, previousExpandedGroupKeys, expandedGroupKeys, direction),
    );
  }

  // 每个过渡 key 一个计时器: 动画放完才把它从集合里摘掉(退场键摘掉即子行卸载)。
  useEffect(() => {
    const timeoutIds = timeoutIdsByKey.current;
    for (const [key, timeoutId] of timeoutIds) {
      if (!transitionKeys.includes(key)) {
        window.clearTimeout(timeoutId);
        timeoutIds.delete(key);
      }
    }
    for (const key of transitionKeys) {
      if (timeoutIds.has(key)) {
        continue;
      }
      timeoutIds.set(
        key,
        window.setTimeout(() => {
          timeoutIds.delete(key);
          updateKeys(setTransitionKeys, (current) => current.filter((currentKey) => currentKey !== key));
        }, motionDurationMs(TRANSITION_ANIMATION_MS)),
      );
    }
  }, [transitionKeys]);

  useEffect(() => {
    const timeoutIds = timeoutIdsByKey.current;
    return () => {
      for (const timeoutId of timeoutIds.values()) {
        window.clearTimeout(timeoutId);
      }
      timeoutIds.clear();
    };
  }, []);

  return transitionKeys;
}

function nextTransitionKeys(
  current: string[],
  previousExpandedGroupKeys: string[],
  expandedGroupKeys: string[],
  direction: TransitionDirection,
): string[] {
  const changedKeys =
    direction === "entering"
      ? expandedGroupKeys.filter((key) => !previousExpandedGroupKeys.includes(key))
      : previousExpandedGroupKeys.filter((key) => !expandedGroupKeys.includes(key));
  // 反向操作立刻作废进行中的过渡: 重新展开的组不再退场, 重新收起的组不再进场。
  const keptKeys = current.filter((key) => keyIsStillTransitioning(key, expandedGroupKeys, direction));
  return Array.from(new Set([...keptKeys, ...changedKeys]));
}

function keyIsStillTransitioning(
  key: string,
  expandedGroupKeys: string[],
  direction: TransitionDirection,
): boolean {
  return direction === "entering" ? expandedGroupKeys.includes(key) : !expandedGroupKeys.includes(key);
}

function updateKeys(setKeys: SetKeys, buildNext: (current: string[]) => string[]) {
  setKeys((current) => {
    const next = buildNext(current);
    return stringListsAreEqual(current, next) ? current : next;
  });
}

function motionDurationMs(fullMs: number): number {
  if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return 0;
  }
  return fullMs;
}

function stringListsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
