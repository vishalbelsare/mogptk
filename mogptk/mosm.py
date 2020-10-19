import numpy as np
#import gpflow
#from gpflow import covariances as cov
#from gpflow.base import TensorLike
#from gpflow.kernels.base import Sum
from .model import model
from .dataset import DataSet
from .sm import _estimate_from_sm
from .kernels import MultiOutputSpectralKernel, MixtureKernel# Noise, Kuu_mosm_vik, Kuf_mosm_vik
from .plot import plot_spectrum
#from .variational_inducing_variables import VariationalInducingFunctions
import matplotlib as mpl
import matplotlib.pyplot as plt

class MOSM(model):
    """
    MOGP with Multi Output Spectral Mixture kernel, as proposed in [1].

    The model contain the dataset and the associated gpflow model, 
    when the mogptk.Model is instanciated the gpflow model is built 
    using random parameters.

    Args:
        dataset (mogptk.dataset.DataSet): DataSet object of data for all channels.
        Q (int, optional): Number of components.
        name (str, optional): Name of the model.
        likelihood (gpflow.likelihoods, optional): Likelihood to use from GPFlow, if None a default exact inference Gaussian likelihood is used.
        variational (bool, optional): If True, use variational inference to approximate function values as Gaussian. If False it will use Monte Carlo Markov Chain.
        sparse (bool, optional): If True, will use sparse GP regression.
        like_params (dict, optional): Parameters to GPflow likelihood.

    Atributes:
        dataset: Constains the mogptk.DataSet associated.
        model: GPflow model.

    Examples:
    >>> import numpy as np
    >>> t = np.linspace(0, 10, 100)
    >>> y1 = np.sin(0.5 * t)
    >>> y2 = 2 * np.sin(0.2 * t)
    >>> import mogptk
    >>> data_list = []
    >>> mogptk.data_list.append(mogptk.Data(t, y1))
    >>> mogptk.data_list.append(mogptk.Data(t, y2))
    >>> model = mogptk.MOSM(data_list, Q=2)
    >>> model.build()
    >>> model.train()
    >>> model.plot_prediction()

    [1] G. Parra and F. Tobar, "Spectral Mixture Kernels for Multi-Output Gaussian Processes", Advances in Neural Information Processing Systems 31, 2017
    """
    def __init__(self, dataset, Q=1, name="MOSM"):
        model.__init__(self, name, dataset)
        self.Q = Q

        spectral = MultiOutputSpectralKernel(
            output_dims=self.dataset.get_output_dims(),
            input_dims=self.dataset.get_input_dims()[0],
        )
        kernel = MixtureKernel(spectral, Q=Q)
        self._build(kernel)

    #def _build(self, kernel, likelihood, variational, sparse, like_params, inducing_variable, **kwargs):
    #    """
    #    Build the model using the given kernel and likelihood. The variational and sparse booleans decide which GPflow model will be used.

    #    Args:
    #        kernel (gpflow.Kernel): Kernel to use.
    #        likelihood (gpflow.likelihoods): Likelihood to use from GPFlow, if None
    #            a default exact inference Gaussian likelihood is used.
    #        variational (bool): If True, use variational inference to approximate
    #            function values as Gaussian. If False it will use Monte carlo Markov Chain.
    #        sparse (bool): If True, will use sparse GP regression.
    #        like_params (dict): Parameters to GPflow likelihood.
    #    """

    #    x, y = self.dataset._to_kernel()

    #    # Gaussian likelihood
    #    if likelihood is None:
    #        if not sparse:
    #            self.model = gpflow.models.GPR((x, y), kernel, **kwargs)
    #        else:
    #            # TODO: it will cause problem if they use other model after this is executed
    #            self.name += ' (sparse variational)'
    #            if isinstance(inducing_variable, VariationalInducingFunctions):
    #                cov.Kuu.add((VariationalInducingFunctions, MultiOutputSpectralMixture), func=Kuu_mosm_vik)
    #                cov.Kuu.add((VariationalInducingFunctions, Sum), func=Kuu_mosm_vik)

    #                cov.Kuf.add((VariationalInducingFunctions, MultiOutputSpectralMixture, TensorLike), func=Kuf_mosm_vik)
    #                cov.Kuf.add((VariationalInducingFunctions, Sum, TensorLike), func=Kuf_mosm_vik)
    #                
    #            self.model = gpflow.models.SGPR((x, y), kernel, inducing_variable=inducing_variable, **kwargs)         
    #                
    #    # MCMC
    #    elif not variational:
    #        self.likelihood = likelihood(**like_params)
    #        if not sparse:
    #            self.name += ' (MCMC approx)'
    #            self.model = gpflow.models.GPMC((x, y), kernel, self.likelihood, **kwargs)
    #        else:
    #            self.name += ' (sparse variational with MCMC approx)'
    #            self.model = gpflow.models.SGPMC((x, y), kernel, self.likelihood, **kwargs)
    #    # Variational
    #    else:
    #        self.likelihood = likelihood(**like_params)
    #        if not sparse:
    #            self.name += ' (variational approx)'
    #            self.model = gpflow.models.VGP((x, y), kernel, self.likelihood, **kwargs)
    #        else:
    #            self.name += ' (sparse variational with variational approx)'
    #            self.model = gpflow.models.SVGP((x, y), kernel, self.likelihood, **kwargs)

    def init_parameters(self, method='BNSE', sm_method='BNSE', sm_opt='BFGS', sm_maxiter=3000, plot=False):
        """
        Initialize kernel parameters.

        The initialization can be done in two ways, the first by estimating the PSD via 
        BNSE (Tobar 2018) and then selecting the greater Q peaks in the estimated spectrum,
        the peaks position, magnitude and width initialize the mean, magnitude and variance
        of the kernel respectively.
        The second way is by fitting independent Gaussian process for each channel, each one
        with SM kernel, using the fitted parameters for initial values of the multioutput kernel.

        In all cases the noise is initialized with 1/30 of the variance 
        of each channel.

        Args:
            method (str, optional): Method of estimation, possible values are 'BNSE' and 'SM'.
            sm_method (str, optional): Method of estimating SM kernels. Only valid in 'SM' mode.
            sm_opt (str, optional): Optimization method for SM kernels. Only valid in 'SM' mode.
            sm_maxiter (str, optional): Maximum iteration for SM kernels. Only valid in 'SM' mode.
            plot (bool, optional): Show the PSD of the kernel after fitting SM kernels. Only valid in 'SM' mode.
        """

        input_dims = self.dataset.get_input_dims()
        output_dims = self.dataset.get_output_dims()

        if method in ['BNSE', 'LS']:
            if method == 'BNSE':
                amplitudes, means, variances = self.dataset.get_bnse_estimation(self.Q)
            else:
                amplitudes, means, variances = self.dataset.get_lombscargle_estimation(self.Q)
            if len(amplitudes) == 0:
                logger.warning('{} could not find peaks for MOSM'.format(method))
                return

            magnitude = np.zeros((output_dims, self.Q))
            for q in range(self.Q):
                mean = np.empty((output_dims,input_dims[0]))
                variance = np.empty((output_dims,input_dims[0]))
                for i in range(output_dims):
                    magnitude[i,q] = amplitudes[i][:,q].mean()
                    mean[i,:] = means[i][:,q] * 2 * np.pi
                    # maybe will have problems with higher input dimensions
                    variance[i,:] = variances[i][:,q] * (4 + 20 * (max(input_dims) - 1)) # 20

                self.model.kernel[q].mean.assign(mean)
                self.model.kernel[q].variance.assign(variance)

            # normalize proportional to channels variances
            for i, channel in enumerate(self.dataset):
                _, y = channel.get_train_data(transformed=True)
                magnitude[i,:] = np.sqrt(magnitude[i,:] / magnitude[i,:].sum() * y.var()) * 2
            
            for q in range(self.Q):
                self.model.kernel[q].magnitude.assign(magnitude[:,q])
            
        elif method == 'SM':
            params = _estimate_from_sm(self.dataset, self.Q, method=sm_method, optimizer=sm_opt, maxiter=sm_maxiter, plot=plot)

            magnitude = np.zeros((output_dims, self.Q))
            for q in range(self.Q):
                magnitude[:,q] = params[q]['weight'].mean(axis=0)

            # normalize proportional to channels variances
            for i, channel in enumerate(self.dataset):
                if magnitude[i,:].sum() == 0:
                    raise Exception("sum of magnitudes equal to zero")
                _, y = channel.get_train_data(transformed=True)
                magnitude[i,:] = np.sqrt(magnitude[i,:] / magnitude[i,:].sum() * y.var()) * 2

            for q in range(self.Q):
                self.model.kernel[q].magnitude.assign(magnitude[:,q])
                self.model.kernel[q].mean.assign(params[q]['mean'])
                self.model.kernel[q].variance.assign(params[q]['scale'] * 2)
        else:
            raise ValueError("valid methods of estimation are 'BNSE', 'LS', or 'SM'")

        #noise = np.empty((output_dims,))
        #for i, channel in enumerate(self.dataset):
        #    _, y = channel.get_train_data(transformed=True)
        #    noise[i] = y.var() / 30
        #self.set_parameter(self.Q, 'noise', noise)

    def plot(self):
        names = self.dataset.get_names()
        nyquist = self.dataset.get_nyquist_estimation()

        means = np.array([self.model.kernel[q].mean() for q in range(self.Q)])
        weights = np.array([self.model.kernel[q].magnitude() for q in range(self.Q)])**2
        scales = np.array([self.model.kernel[q].variance() for q in range(self.Q)])
        plot_spectrum(means, scales, weights=weights, nyquist=nyquist, titles=names)

    def plot_psd(self, figsize=(20, 14), title=''):
        """
        Plot power spectral density and power cross spectral density.

        Note: Implemented only for 1 input dimension.
        """

        cross_params = self._get_cross_parameters()
        m = self.dataset.get_output_dims()

        fig, axes = plt.subplots(m, m, sharex=False, figsize=figsize, squeeze=False)
        for i in range(m):
            for j in range(i+1):
                self._plot_power_cross_spectral_density(
                    axes[i, j],
                    cross_params,
                    channels=(i, j))

        plt.tight_layout()
        return fig, axes

    def _plot_power_cross_spectral_density(self, ax, params, channels=(0, 0)):
        """
        Plot power cross spectral density given axis.

        Args:
            ax (matplotlib.axis): Axis to plot to.
            params(dict): Kernel parameters.
            channels (tuple of ints): Channels to use.
        """
        i = channels[0]
        j = channels[1]

        mean = params['mean'][i, j, 0, :]
        cov = params['covariance'][i, j, 0, :]
        delay = params['delay'][i, j, 0, :]
        magn = params['magnitude'][i, j, :]
        phase = params['phase'][i, j, :]

        
        w_high = (mean + 2* np.sqrt(cov)).max()

        w = np.linspace(-w_high, w_high, 1000)

        # power spectral density
        if i==j:
            psd_total = np.zeros(len(w))
            for q in range(self.Q):
                psd_q = np.exp(-0.5 * (w - mean[q])**2 / cov[q])
                psd_q += np.exp(-0.5 * (w + mean[q])**2 / cov[q])
                psd_q *= magn[q] * 0.5

                ax.plot(w, psd_q, '--r', lw=0.5)

                psd_total += psd_q
            ax.plot(w, psd_total, 'r', lw=2.1, alpha=0.7)
        # power cross spectral density
        else:
            psd_total = np.zeros(len(w)) + 0.j
            for q in range(self.Q):
                psd_q = np.exp(-0.5 * (w - mean[q])**2 / cov[q] + 1.j * (w * delay[q] + phase[q]))
                psd_q += np.exp(-0.5 * (w + mean[q])**2 / cov[q] + 1.j * (w * delay[q] + phase[q]))
                psd_q *= magn[q] * 0.5

                ax.plot(w, np.real(psd_q), '--b', lw=0.5)
                ax.plot(w, np.imag(psd_q), '--g', lw=0.5)
            
                psd_total += psd_q
            ax.plot(w, np.real(psd_total), 'b', lw=1.2, alpha=0.7)
            ax.plot(w, np.imag(psd_total), 'g', lw=1.2, alpha=0.7)
        ax.set_yticks([])
        return

    def info(self):
        for channel in range(self.dataset.get_output_dims()):
            for q in range(self.Q):
                mean = self.model.kernel[q].mean().numpy()[channel,:]
                var = self.model.kernel[q].variance().numpy()[channel,:]
                if np.linalg.norm(mean) < np.linalg.norm(var):
                    print("‣ MOSM approaches RBF kernel for q=%d in channel='%s'" % (q, self.dataset[channel].name))

    def _get_cross_parameters(self):
        """
        Obtain cross parameters from MOSM

        Returns:
            cross_params(dict): Dictionary with the cross parameters, 'covariance', 'mean',
            'magnitude', 'delay' and 'phase'. Each one a output_dim x output_dim x input_dim x Q
            array with the cross parameters, with the exception of 'magnitude' and 'phase' where 
            the cross parameters are a output_dim x output_dim x Q array.
            NOTE: this assumes the same input dimension for all channels.
        """
        m = self.dataset.get_output_dims()
        d = self.dataset.get_input_dims()[0]
        Q = self.Q

        cross_params = {}

        cross_params['covariance'] = np.zeros((m, m, d, Q))
        cross_params['mean'] = np.zeros((m, m, d, Q))
        cross_params['magnitude'] = np.zeros((m, m, Q))
        cross_params['delay'] = np.zeros((m, m, d, Q))
        cross_params['phase'] = np.zeros((m, m, Q))

        for q in range(Q):
            for i in range(m):
                for j in range(m):
                    var_i = self.model.kernel[q].variance().numpy()[i,:]
                    var_j = self.model.kernel[q].variance().numpy()[j,:]
                    mu_i = self.model.kernel[q].mean().numpy()[i,:]
                    mu_j = self.model.kernel[q].mean().numpy()[j,:]
                    w_i = self.model.kernel[q].magnitude().numpy()[i]
                    w_j = self.model.kernel[q].magnitude().numpy()[j]
                    sv = var_i + var_j

                    # cross covariance
                    cross_params['covariance'][i, j, :, q] = 2 * (var_i * var_j) / sv
                    # cross mean
                    cross_mean_num = var_i.dot(mu_j) + var_j.dot(mu_i)
                    cross_params['mean'][i, j, :, q] = cross_mean_num / sv
                    # cross magnitude
                    exp_term = -1/4 * ((mu_i - mu_j)**2 / sv).sum()
                    cross_params['magnitude'][i, j, q] = w_i * w_j * np.exp(exp_term)
            if m>1:
                # cross phase
                phase_q = self.model.kernel[q].phase().numpy()
                cross_params['phase'][:, :, q] = np.subtract.outer(phase_q, phase_q)
                for n in range(d):
                    # cross delay        
                    delay_n_q = self.model.kernel[q].delay().numpy()[:,n]
                    cross_params['delay'][:, :, n, q] = np.subtract.outer(delay_n_q, delay_n_q)

        return cross_params
