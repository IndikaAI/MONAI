# Copyright 2020 - 2021 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging

import maxflow
import numpy as np
from scipy.special import softmax

logger = logging.getLogger(__name__)


def get_eps(data):
    return np.finfo(data.dtype).eps


def maxflow2d(image, prob, lamda=5, sigma=0.1):
    # lamda: weight of smoothing term
    # sigma: std of intensity values
    return maxflow.maxflow2d(image, prob, (lamda, sigma))


def maxflow3d(image, prob, lamda=5, sigma=0.1):
    # lamda: weight of smoothing term
    # sigma: std of intensity values
    return maxflow.maxflow3d(image, prob, (lamda, sigma))


def interactive_maxflow2d(image, prob, seed, lamda=5, sigma=0.1):
    # lamda: weight of smoothing term
    # sigma: std of intensity values
    return maxflow.interactive_maxflow2d(image, prob, seed, (lamda, sigma))


def interactive_maxflow3d(image, prob, seed, lamda=5, sigma=0.1):
    # lamda: weight of smoothing term
    # sigma: std of intensity values
    return maxflow.interactive_maxflow3d(image, prob, seed, (lamda, sigma))


def make_iseg_unary(
    prob,
    scribbles,
    scribbles_bg_label=2,
    scribbles_fg_label=3,
):
    """
    Implements ISeg unary term from the following paper:
    Wang, Guotai, et al. "Interactive medical image segmentation using deep learning with image-specific fine tuning."
    IEEE transactions on medical imaging 37.7 (2018): 1562-1573. (preprint: https://arxiv.org/pdf/1710.04043.pdf)
    ISeg unary term is constructed using Equation 7 on page 4 of the above mentioned paper.
    """

    # fetch the data for probabilities and scribbles
    prob_shape = list(prob.shape)
    scrib_shape = list(scribbles.shape)

    # check if they have compatible shapes
    if prob_shape[1:] != scrib_shape[1:]:
        raise ValueError("shapes for prob and scribbles dont match")

    # expected input shape is [1, X, Y, [Z]], exit if first dimension doesnt comply
    if scrib_shape[0] != 1:
        raise ValueError("scribbles should have single channel first, received {}".format(scrib_shape[0]))

    # unfold a single prob for background into bg/fg prob (if needed)
    if prob_shape[0] == 1:
        prob = np.concatenate([prob, 1.0 - prob], axis=0)

    mask = np.concatenate([scribbles == scribbles_bg_label, scribbles == scribbles_fg_label], axis=0)

    # issue a warning if no scribbles detected, the algorithm will still work
    # just need to inform user/researcher - in case it is unexpected
    if not np.any(mask[0, ...]):
        logging.info(
            "warning: no background scribbles received with label {}, available in scribbles {}".format(
                scribbles_bg_label, np.unique(scribbles)
            )
        )

    if not np.any(mask[1, ...]):
        logging.info(
            "warning: no foreground scribbles received with label {}, available in scribbles {}".format(
                scribbles_fg_label, np.unique(scribbles)
            )
        )

    # copy probabilities
    unary_term = np.copy(prob)

    # for numerical stability, get rid of zeros
    eps = get_eps(unary_term)

    equal_term = 1.0 - eps
    no_equal_term = eps

    # update unary with Equation 7
    unary_term[mask] = equal_term
    mask = np.flip(mask, axis=0)
    unary_term[mask] = no_equal_term

    return unary_term


def make_histograms(image, scrib, scribbles_bg_label, scribbles_fg_label, bins=32):
    # collect background voxels
    values = image[scrib == scribbles_bg_label]
    # generate histogram for background
    bg_hist, _ = np.histogram(values, bins=bins, range=(0, 1), density=True)

    # collect foreground voxels
    values = image[scrib == scribbles_fg_label]
    # generate histrogram for foreground
    fg_hist, fg_bin_edges = np.histogram(values, bins=bins, range=(0, 1), density=True)

    # calculate scale to normalise histogram, such that it returns a true probability
    scale = fg_bin_edges[1] - fg_bin_edges[0]

    # normalise histograms and return
    return (bg_hist * scale).astype(np.float32), (fg_hist * scale).astype(np.float32), fg_bin_edges


def make_likelihood_image_histogram(image, scrib, scribbles_bg_label, scribbles_fg_label, return_prob=True):
    # normalise image in range [0, 1] if needed
    min_img = np.min(image)
    max_img = np.max(image)
    if min_img < 0.0 or max_img > 1.0:
        image = (image - min_img) / (max_img - min_img)

    # generate histograms for background/foreground
    bg_hist, fg_hist, bin_edges = make_histograms(image, scrib, scribbles_bg_label, scribbles_fg_label)

    # lookup values for each voxel for generating background/foreground probabilities
    dimage = np.digitize(image, bin_edges[:-1]) - 1
    fprob = fg_hist[dimage]
    bprob = bg_hist[dimage]
    retprob = np.concatenate([bprob, fprob], axis=0)

    # renormalise
    retprob = softmax(retprob, axis=0)

    # if needed, convert to discrete labels instead of probability
    if not return_prob:
        retprob = np.expand_dims(np.argmax(retprob, axis=0), axis=0).astype(np.float32)

    return retprob