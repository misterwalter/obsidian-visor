#!/usr/bin/env python3
"""Trace the people in a photograph into an OpenPose skeleton image, for the pose
controls. Runs with the pose tool's own Python, inside media_wall.sh, with no network:
the models are given as files.

    trace_pose.py <photo> <out.png> <detector.onnx> <pose.onnx> [body|wholebody] [min-score]

Writes coloured stick figures on black, the same size as the photo, one figure per
person found, and prints one line per person with how sure the model was. "body" draws
the 18 body points only, which is what the pose controls were trained on; "wholebody"
adds hands and face, which steer hands better and faces worse.

Beside the skeleton it writes <out>.hands.json: a box around each hand found, for
redrawing hands afterwards; and <out>.keypoints.json: each person's points as
[x, y, score], in OpenPose order, for motion capture.
"""

import contextlib
import json
import sys

import cv2
import numpy as np
from rtmlib import Wholebody, draw_skeleton


def main(argv):
    photo, out, detector, pose = argv[1:5]
    parts = argv[5] if len(argv) > 5 else "body"
    min_score = float(argv[6]) if len(argv) > 6 else 0.3
    image = cv2.imread(photo)
    if image is None:
        sys.exit(f"trace_pose: cannot read {photo}")
    # rtmlib says which models it loaded on standard output, which is this program's answer: to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        model = Wholebody(det=detector, det_input_size=(640, 640), pose=pose, pose_input_size=(288, 384),
                          to_openpose=True, backend="onnxruntime", device="cpu")
        keypoints, scores = model(image)
    # Each hand's box, from its 21 points (COCO-wholebody order: left 91-111, right 112-132),
    # padded by half its size, since a hand's outline reaches past its joints.
    hands = []
    for person, score in zip(keypoints, scores):
        for name, lo, hi in (("left", 91, 112), ("right", 112, 133)):
            pts = person[lo:hi][score[lo:hi] >= min_score]
            if len(pts) < 8:
                continue
            x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0)
            pad = max(x1 - x0, y1 - y0) * 0.5 + 8
            hands.append({"hand": name, "x": int(max(0, x0 - pad)), "y": int(max(0, y0 - pad)),
                          "w": int(min(image.shape[1], x1 + pad) - max(0, x0 - pad)),
                          "h": int(min(image.shape[0], y1 + pad) - max(0, y0 - pad))})
    with open(out + ".hands.json", "w") as f:
        json.dump(hands, f)
    if parts == "body":
        keypoints, scores = keypoints[:, :18], scores[:, :18]
    with open(out + ".keypoints.json", "w") as f:
        json.dump([[[round(float(x), 1), round(float(y), 1), round(float(s), 3)] for (x, y), s in zip(person, score)]
                   for person, score in zip(keypoints, scores)], f)
    canvas = np.zeros_like(image)
    # Line weight follows the image size: the controls were trained on thin limbs.
    weight = min(8, max(3, min(image.shape[:2]) // 250))
    canvas = draw_skeleton(canvas, keypoints, scores, openpose_skeleton=True, kpt_thr=min_score,
                           radius=weight, line_width=weight)
    cv2.imwrite(out, canvas)
    people = 0
    for person, score in zip(keypoints, scores):
        body = score[:18]
        seen = int((body >= min_score).sum())
        if seen >= 4:  # fewer points than that is a fragment, not a person
            people += 1
            # Scores are not bounded at 1; report how many of the points were found clearly.
            sure = int((body >= 0.6).sum())
            print(f"person {people}: {seen} of 18 body points found, {sure} of them clearly")
    if people == 0:
        print("no people found")
    print(f"{len(hands)} hands")


if __name__ == "__main__":
    main(sys.argv)
