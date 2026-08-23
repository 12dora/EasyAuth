/** 权限组展开与收起动画的过渡 key 生命周期。 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

const EXIT_ANIMATION_MS = 160;

type TransitionDirection = "entering" | "exiting";
type SetKeys = Dispatch<SetStateAction<string[]>>;

export function useGroupTransitionKeys(
  expandedGroupKeys: string[],
  direction: TransitionDirection,
): string[] {
  const previousExpandedGroupKeys = useRef(expandedGroupKeys);
  const timeoutIdsByKey = useRef(new Map<string, number>());
  const generationByKey = useRef(new Map<string, number>());
  const [transitionKeys, setTransitionKeys] = useState<string[]>([]);

  useEffect(() => {
    const previousKeys = previousExpandedGroupKeys.current;
    const changedKeys =
      direction === "entering"
        ? expandedGroupKeys.filter((key) => !previousKeys.includes(key))
        : previousKeys.filter((key) => !expandedGroupKeys.includes(key));
    previousExpandedGroupKeys.current = expandedGroupKeys;
    if (direction === "entering") {
      return updateEnteringKeys(expandedGroupKeys, changedKeys, setTransitionKeys);
    }
    updateExitingKeys(
      expandedGroupKeys,
      changedKeys,
      setTransitionKeys,
      timeoutIdsByKey,
      generationByKey,
    );
  }, [direction, expandedGroupKeys]);

  useEffect(() => {
    const timeoutIds = timeoutIdsByKey.current;
    return () => {
      for (const timeoutId of timeoutIds.values()) {
        window.clearTimeout(timeoutId);
      }
      timeoutIds.clear();
    };
  }, []);

  return useMemo(
    () =>
      transitionKeys.filter((key) =>
        direction === "entering" ? expandedGroupKeys.includes(key) : !expandedGroupKeys.includes(key),
      ),
    [direction, expandedGroupKeys, transitionKeys],
  );
}

function updateEnteringKeys(expandedGroupKeys: string[], addedGroupKeys: string[], setKeys: SetKeys) {
  if (addedGroupKeys.length === 0) {
    updateKeys(setKeys, (current) => current.filter((key) => expandedGroupKeys.includes(key)));
    return;
  }
  updateKeys(setKeys, (current) => Array.from(new Set([...current, ...addedGroupKeys])));
  const timeoutId = window.setTimeout(() => {
    updateKeys(setKeys, (current) => current.filter((key) => !addedGroupKeys.includes(key)));
  }, motionDurationMs(EXIT_ANIMATION_MS));
  return () => window.clearTimeout(timeoutId);
}

function updateExitingKeys(
  expandedGroupKeys: string[],
  removedGroupKeys: string[],
  setKeys: SetKeys,
  timeoutIdsByKey: MutableRefObject<Map<string, number>>,
  generationByKey: MutableRefObject<Map<string, number>>,
) {
  cancelReexpandedKeys(expandedGroupKeys, timeoutIdsByKey.current, generationByKey.current);
  if (removedGroupKeys.length === 0) {
    updateKeys(setKeys, (current) => current.filter((key) => !expandedGroupKeys.includes(key)));
    return;
  }
  updateKeys(setKeys, (current) => Array.from(new Set([...current, ...removedGroupKeys])));
  for (const key of removedGroupKeys) {
    startExitTimer(key, setKeys, timeoutIdsByKey.current, generationByKey.current);
  }
}

function cancelReexpandedKeys(expandedKeys: string[], timers: Map<string, number>, generations: Map<string, number>) {
  for (const key of expandedKeys) {
    const existingTimer = timers.get(key);
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
      timers.delete(key);
    }
    generations.set(key, (generations.get(key) ?? 0) + 1);
  }
}

function startExitTimer(key: string, setKeys: SetKeys, timers: Map<string, number>, generations: Map<string, number>) {
  const generation = (generations.get(key) ?? 0) + 1;
  generations.set(key, generation);
  const existingTimer = timers.get(key);
  if (existingTimer !== undefined) {
    window.clearTimeout(existingTimer);
  }
  const timeoutId = window.setTimeout(() => {
    timers.delete(key);
    if (generations.get(key) !== generation) {
      return;
    }
    updateKeys(setKeys, (current) => current.filter((currentKey) => currentKey !== key));
  }, motionDurationMs(EXIT_ANIMATION_MS));
  timers.set(key, timeoutId);
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
