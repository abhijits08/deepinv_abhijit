import numpy as np
import torch
import torch.nn as nn

from pytorch_wavelets import DWTForward, DWTInverse  # (or import DWT, IDWT)


class WaveletDict(nn.Module):
    '''
    WORK IN PROGRESS
    Torch implementation of the proximal operator of sparsity in a redundant wavelet dictionary domain (SARA dictionary).

    Minimisation is performed with a dual forward-backward algorithm.

    TODO: detail doc + perform tests
    '''

    def __init__(self, y_shape, ths=0.1, max_it=100, conv_crit=1e-3, eps=1e-6, gamma=1., verbose=False,
                 list_wv=['db1', 'db2', 'db3', 'db4', 'db5', 'db6', 'db7', 'db8'], dtype=torch.FloatTensor, level=3):

        super(WaveletDict, self).__init__()

        self.dtype = dtype
        self.max_it = max_it
        self.ths = ths
        self.gamma = gamma
        self.eps = eps
        self.list_wv = list_wv
        self.conv_crit = conv_crit
        self.dict = SARA_dict(torch.zeros(y_shape).type(self.dtype), level=level, list_wv=list_wv)
        self.verbose = verbose

        self.v1_low = None
        self.v1_high = None
        self.r1 = None
        self.vy1 = None
        self.x_ = None

    def prox_l1(self, x, ths=0.1):
        return torch.maximum(torch.Tensor([0]).type(x.dtype), x - ths) + torch.minimum(torch.Tensor([0]).type(x.dtype),
                                                                                       x + ths)

    def forward(self, y):

        if self.v1_low is None:
            self.v1_low, self.v1_high = self.dict.Psit(y)  # initialization of L1 dual variable
        if self.r1 is None:
            self.r1 = torch.clone(self.v1_high)
            self.r1_low = torch.clone(self.v1_low)
        if self.vy1 is None:
            self.vy1 = torch.clone(self.v1_high)
        if self.x_ is None:
            self.x_ = torch.zeros_like(y)

        for it in range(self.max_it):

            x_old = torch.clone(self.x_)

            v_up = self.dict.Psi(self.v1_low, self.v1_high)
            self.x_ = torch.maximum(self.x_ - self.gamma * (v_up + self.x_ - y),
                                    torch.Tensor([0.]).type(self.x_.dtype))  # Projection on [0, +\infty)
            prev_xsol = 2. * self.x_ - x_old
            self.v1_low, self.r1 = self.dict.Psit(prev_xsol)
            self.v1_high = self.v1_high + 0.5 * self.r1 - self.prox_l1(self.v1_high + 0.5 * self.r1,
                                                                       ths=0.5 * self.ths)  # weights on ths
            self.v1_low = self.v1_low + 0.5 * self.r1_low - self.prox_l1(self.v1_low + 0.5 * self.r1_low,
                                                                         ths=0. * self.ths)  # weights on ths

            rel_err = torch.linalg.norm(self.x_ - x_old) / torch.linalg.norm(x_old + self.eps)
            if rel_err < self.conv_crit:
                break

            if self.verbose:
                if it % 1 == 0:
                    cost = torch.abs(self.r1).sum()
                    print('Iter ', str(it), ' rel crit = ', rel_err, ' l1 cost = ', cost)

        if self.verbose:
            print('Converged after ', str(it), ' iterations; relative err = ', rel_err)

        return self.x_


def coef2vec(coef, Nc, Nx, Ny):
    """
    Convert wavelet coefficients to an array-type vector, inverse operation of vec2coef.
    The initial wavelet coefficients are stocked in a list as follows:
        [cAn, (cHm, cVn, cDn), ..., (cH1, cV1, cD1)],
    and each element is a 2D array.
    After the conversion, the returned vector is as follows:
    [cAn.flatten(), cHn.flatten(), cVn.flatten(), cDn.flatten(), ...,cH1.flatten(), cV1.flatten(), cD1.flatten()].
    """
    vec = torch.Tensor([])
    bookkeeping = []
    for ele in coef:
        if type(ele) == tuple:
            bookkeeping.append((np.shape(ele[0])))
            for wavcoef in ele:
                vec = torch.concat((vec, wavcoef.flatten()))
        else:
            bookkeeping.append((np.shape(ele)))
            vec = torch.concat((vec, ele.flatten()))
    return vec, bookkeeping


def vec2coef(vec, bookkeeping):
    """
    Convert an array-type vector to wavelet coefficients, inverse operation of coef2vec.
    The initial vector is stocked in a 1D array as follows:
    [cAn.flatten(), cHn.flatten(), cVn.flatten(), cDn.flatten(), ..., cH1.flatten(), cV1.flatten(), cD1.flatten()].
    After the conversion, the returned wavelet coefficient is in the form of the list as follows:
        [cAn, (cHm, cVn, cDn), ..., (cH1, cV1, cD1)],
    and each element is a 2D array. This list can be passed as the argument in pywt.waverec2.
    """
    ind = 0
    coef = []
    for ele in bookkeeping:
        indnext = ele[0] * ele[1] * ele[2]
        coef.append((torch.reshape(vec[ind:ind + indnext], ele),
                     torch.reshape(vec[ind + indnext:ind + 2 * indnext], ele),
                     torch.reshape(vec[ind + 2 * indnext:ind + 3 * indnext], ele)))
        ind += 3 * indnext

    return coef


def torch2pywt_format(Yl, Yh):
    '''
    Takes as input a torch wavelet element; outputs a list of tensors in the format of pywt (numpy library).
    '''
    Yh_ = [torch.unbind(Yh[-(level + 1)].squeeze(), dim=0) for level in range(len(Yh))]

    return Yl, Yh_


def pywt2torch_format(Yh_):
    '''
    Takes as input a torch wavelet element; outputs a list of tensors in the format of pywt (numpy library).
    '''
    Yh_rev = Yh_[::-1]
    Yh = [torch.stack(Yh_cur).unsqueeze(0) for Yh_cur in Yh_rev]

    return Yh


def wavedec_asarray(im, wv='db8', level=3):
    xfm = DWTForward(J=level, mode='zero', wave=wv)
    Yl, Yh = xfm(im)
    Yl, Yh_ = torch2pywt_format(Yl, Yh)
    wd, book = coef2vec(Yh_, im.shape[-3], im.shape[-2], im.shape[-1])

    return Yl.flatten(), Yl.shape, wd, book


def waverec_asarray(Yl_flat, Yl_shape, wd, book, wv='db8'):
    wc = vec2coef(wd, book)
    Yl = Yl_flat.reshape(Yl_shape)

    Yh = pywt2torch_format(wc)
    ifm = DWTInverse(mode='zero', wave=wv)
    Y = ifm((Yl, Yh))

    return Y


class SARA_dict(nn.Module):

    def __init__(self, im, level, list_wv=['db1', 'db2', 'db3', 'db4', 'db5', 'db6', 'db7', 'db8']):

        super(SARA_dict, self).__init__()

        self.level = level
        self.list_coeffs_lf = []
        self.list_coeffs = []
        self.list_b = []
        self.list_lfshape = []
        self.list_wv = list_wv

        for wv_cur in self.list_wv:
            low_cur, lf_shape_cur, c_cur, b_cur = wavedec_asarray(im, wv_cur, level=level)
            self.list_coeffs_lf.append(low_cur.shape[0])
            self.list_coeffs.append(len(c_cur))
            self.list_b.append(b_cur)
            self.list_lfshape.append(lf_shape_cur)

        self.list_coeffs_cumsum = np.cumsum(self.list_coeffs)
        self.list_coeffs_lf_cumsum = np.cumsum(self.list_coeffs_lf)

    def Psit(self, x):

        list_tensors_lf = [wavedec_asarray(x, wv_cur, level=self.level)[0] for wv_cur in self.list_wv]
        list_tensors_hf = [wavedec_asarray(x, wv_cur, level=self.level)[2] for wv_cur in self.list_wv]

        out_hf = torch.concat(list_tensors_hf)
        out_lf = torch.concat(list_tensors_lf)

        return out_lf / np.sqrt(len(self.list_wv)), out_hf / np.sqrt(len(self.list_wv))

    def Psi(self, y_lf, y_hf):

        out = waverec_asarray(y_lf[:self.list_coeffs_lf_cumsum[0]], self.list_lfshape[0],
                              y_hf[:self.list_coeffs_cumsum[0]], self.list_b[0], wv=self.list_wv[0])

        for _ in range(len(self.list_coeffs_cumsum) - 1):
            out = out + waverec_asarray(y_lf[self.list_coeffs_lf_cumsum[_]:self.list_coeffs_lf_cumsum[_ + 1]],
                                        self.list_lfshape[_ + 1],
                                        y_hf[self.list_coeffs_cumsum[_]:self.list_coeffs_cumsum[_ + 1]],
                                        self.list_b[_ + 1], wv=self.list_wv[_ + 1])

        return out / np.sqrt(len(self.list_wv))
