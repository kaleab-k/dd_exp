import math
import numpy as np
import torch
from torch import nn
import matplotlib.pyplot as plt

from matplotlib.patches import ConnectionPatch

import copy
import random
import concurrent.futures

import seaborn as sns
from sklearn.preprocessing import minmax_scale
from matplotlib import cm

import os

## Distributions 

def generate_gaussian_parity(n, cov_scale=1, angle_params=None, k=1, acorn=None):
    """ Generate Gaussian XOR, a mixture of four Gaussians elonging to two classes. 
    Class 0 consists of negative samples drawn from two Gaussians with means (−1,−1) and (1,1)
    Class 1 comprises positive samples drawn from the other Gaussians with means (1,−1) and (−1,1) 
    """
#     means = [[-1.5, -1.5], [1.5, 1.5], [1.5, -1.5], [-1.5, 1.5]]
    means = [[-1, -1], [1, 1], [1, -1], [-1, 1]]
    blob = np.concatenate(
        [
            np.random.multivariate_normal(
                mean, cov_scale * np.eye(len(mean)), size=int(n / 4)
            )
            for mean in means
        ]
    )

    X = np.zeros_like(blob)
    Y = np.concatenate([np.ones((int(n / 4))) * int(i < 2) for i in range(len(means))])
    X[:, 0] = blob[:, 0] * np.cos(angle_params * np.pi / 180) + blob[:, 1] * np.sin(
        angle_params * np.pi / 180
    )
    X[:, 1] = -blob[:, 0] * np.sin(angle_params * np.pi / 180) + blob[:, 1] * np.cos(
        angle_params * np.pi / 180
    )
    return X, Y.astype(int)
        

## Network functions

# Model 
class Net(nn.Module):
    """ DeepNet class
    A deep net architecture with `n_hidden` layers, 
    each having `hidden_size` nodes.
    """
    def __init__(self, in_dim, out_dim, hidden_size=10, n_hidden=2,
                activation=torch.nn.ReLU(), bias=False, penultimate=False, bn=False):
        super(Net, self).__init__()

        module = nn.ModuleList()
        module.append(nn.Linear(in_dim, hidden_size, bias=bias))

        for ll in range(n_hidden):
            module.append( activation )
            if bn:
                module.append( nn.BatchNorm1d( hidden_size ) )
            module.append( nn.Linear(hidden_size, hidden_size, bias=bias) )      
        
        if penultimate:
            module.append( activation )
            if bn:
                module.append( nn.BatchNorm1d( hidden_size ) )
            module.append( nn.Linear(hidden_size, 2, bias=bias) )
            hidden_size = 2
            
        module.append( activation )
        if bn:
            module.append( nn.BatchNorm1d( hidden_size ) )
        module.append( nn.Linear(hidden_size, out_dim, bias=bias) )

        self.sequential = nn.Sequential(*module)

    def forward(self, x):
        return self.sequential(x)

# functions
def weight_reset(m):
    if isinstance(m, torch.nn.Conv2d) or isinstance(m, torch.nn.Linear):
        m.reset_parameters()

def train_model(model, train_x, train_y, multi_label=False, verbose=False):
    """ 
     Train the model given the training data
    """
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_func = torch.nn.BCEWithLogitsLoss()
    
    losses = []
        
    for step in range(1000):
        optimizer.zero_grad()
        outputs = model(train_x)
        if multi_label:
            train_y = train_y.type_as(outputs)
        
        loss=loss_func(outputs, train_y)
        trainL = loss.detach().item()
        if verbose and (step % 500 == 0):
            print("train loss = ", trainL)
        losses.append(trainL)
        loss.backward()
        optimizer.step()
    
    return losses
                
def get_model(hidden_size=20, n_hidden=5, in_dim=2, out_dim=1, penultimate=False, use_cuda=True, bn=False):
    """
     Initialize the model and send to gpu
    """
    in_dim = in_dim
    out_dim = out_dim #1
    model = Net(in_dim, out_dim, n_hidden=n_hidden, hidden_size=hidden_size,
                activation=torch.nn.ReLU(), bias=True, penultimate=penultimate, bn=bn)
    
    if use_cuda:
        model=model.cuda()
        
    return model

            
def get_dataset(N=1000, one_hot=False, cov_scale=1, include_hybrid=False):
    """
     Generate the Gaussian XOR dataset and move to gpu
    """
    use_cuda = torch.cuda.is_available()
    if use_cuda:
        torch.cuda.set_device(0)
        torch.set_default_tensor_type(torch.cuda.FloatTensor)
        
    if include_hybrid:
        D_x, D_y = generate_gaussian_parity(cov_scale=cov_scale, n=2*N, angle_params=0)
        D_perm = np.random.permutation(2*N)
        D_x, D_y  = D_x[D_perm,:], D_y[D_perm]
        train_x, train_y = D_x[:N], D_y[:N]
        ghost_x, ghost_y = D_x[N:], D_y[N:]
        hybrid_sets = []
        rand_idx = random.sample(range(0,N-1), N//10)
        for rand_i in rand_idx:
            hybrid_x, hybrid_y = np.copy(train_x), np.copy(train_y)
            hybrid_x[rand_i], hybrid_y[rand_i] = ghost_x[rand_i], ghost_y[rand_i]
            hybrid_x = torch.FloatTensor(hybrid_x)
            hybrid_y = (torch.FloatTensor(hybrid_y).unsqueeze(-1))
            hybrid_x, hybrid_y = hybrid_x.cuda(), hybrid_y.cuda()
            hybrid_sets.append((hybrid_x, hybrid_y))
    else:
        train_x, train_y = generate_gaussian_parity(cov_scale=cov_scale, n=N, angle_params=0)
        train_perm = np.random.permutation(N)
        train_x, train_y = train_x[train_perm,:], train_y[train_perm] 
    test_x, test_y = generate_gaussian_parity(cov_scale=cov_scale, n=2*N, angle_params=0)
    
    test_perm = np.random.permutation(2*N)
    test_x, test_y  = test_x[test_perm,:], test_y[test_perm]
    
    train_x = torch.FloatTensor(train_x)
    test_x = torch.FloatTensor(test_x)

    train_y = (torch.FloatTensor(train_y).unsqueeze(-1))#[:,0]
    test_y = (torch.FloatTensor(test_y).unsqueeze(-1))#[:,0]
    
    if one_hot:
        train_y = torch.nn.functional.one_hot(train_y[:,0].to(torch.long))
        test_y = torch.nn.functional.one_hot(test_y[:,0].to(torch.long))
    
    # move to gpu
    if use_cuda:
        train_x, train_y = train_x.cuda(), train_y.cuda()
        test_x, test_y = test_x.cuda(), test_y.cuda()
        
    if include_hybrid:
        return train_x, train_y, test_x, test_y, hybrid_sets
    
    return train_x, train_y, test_x, test_y

                          
def run_experiment(depth, iterations, reps=100, width=3, cov_scale=1):
    """
     Main function to run the `Increasing Depth` 
     and `Increasing Width` experiments 
    """
    result = lambda: None
    
    xx, yy = np.meshgrid(np.arange(-2, 2, 4 / 100), np.arange(-2, 2, 4 / 100))
    true_posterior = np.array([pdf(x) for x in (np.c_[xx.ravel(), yy.ravel()])])
    
    rep_full_list = []
    imgs = []
#     train_x, train_y, test_x, test_y = get_dataset(cov_scale=cov_scale)
    train_x, train_y, test_x, test_y, hybrid_sets = get_dataset(N=1000, cov_scale=cov_scale, include_hybrid=True)
    depth = depth
    penultimate_vars_reps = []

    for rep in range(reps):#25

        print('rep: ' + str(rep))

        ## Shffle train set labels for activation variation panel
        # train_y_tmp = torch.clone(train_y)
        # train_y[train_y_tmp==0] = 1
        # train_y[train_y_tmp==1] = 0
        # test_y_tmp = torch.clone(test_y)
        # test_y[test_y_tmp==0] = 1
        # test_y[test_y_tmp==1] = 0

        # del train_y_tmp
        losses_list = []
        num_pars = []
        num_poly = []
        hellinger_list = []
        gini_train, gini_test = [], []

        
        train_loss_list = []
        test_loss_list = []
        train_acc_list = []
        test_acc_list = []

        penultimate_acts = []
        penultimate_nodes = []
        penultimate_err = []
        penultimate_poly = []
        penultimate_vars = []

        avg_stab_list = []
        bias_list = []
        var_list = []

        for i in range(1, iterations):
            print('now running', i)

            ## Increasing Depth
            if depth:
                if i < 5:
                    model = get_model(n_hidden = i, hidden_size=i, penultimate=False, bn=False)
                else:
                    model = get_model(n_hidden = i, penultimate=False, bn=False)
            else:
            ## Increasing Width
                model = get_model(hidden_size = i, n_hidden=width, penultimate=False, bn=False)

            n_par = sum(p.numel() for p in model.parameters())

            losses = train_model(model, train_x, train_y)

            poly, penultimate_act = get_polytopes(model, train_x, penultimate=False)
            n_poly = len(np.unique(poly[0]))

            if depth:
                n_node = i*20 if i>5 else i*i
            else:
                n_node = i*3
            
            penultimate_acts.append(penultimate_act)
            penultimate_vars.append(list(np.var(penultimate_act, axis=0)))

            with torch.no_grad():
                pred_train, pred_test = model(train_x), model(test_x)
                
                gini_impurity_train = gini_impurity_mean(poly[0], torch.sigmoid(pred_train).round().cpu().data.numpy())
                poly_test, _ = get_polytopes(model, test_x, penultimate=False)
                gini_impurity_test = gini_impurity_mean(poly_test[0], torch.sigmoid(pred_test).round().cpu().data.numpy())
                
                rf_posteriors_grid = model(torch.FloatTensor(np.c_[xx.ravel(), yy.ravel()]).cuda())
                class_1_posteriors = torch.sigmoid(rf_posteriors_grid).detach().cpu().numpy()
                pred_proba = np.concatenate([1 - class_1_posteriors, class_1_posteriors], axis = 1)
                
                hellinger_loss = hellinger_explicit(pred_proba, true_posterior)

                train_y = train_y.type_as(pred_train)
                test_y  = test_y.type_as(pred_test)
                train_loss = torch.nn.BCEWithLogitsLoss()(pred_train, train_y)
    #             train_acc = (torch.argmax(pred_train,1) == torch.argmax(train_y,1)).sum().cpu().data.numpy().item() / train_y.size(0)
                train_acc = (torch.sigmoid(pred_train).round() == train_y).sum().cpu().data.numpy().item() / train_y.size(0)
                test_loss = torch.nn.BCEWithLogitsLoss()(pred_test, test_y)
    #             test_acc = (torch.argmax(pred_test,1) == torch.argmax(test_y,1)).sum().cpu().data.numpy().item() / test_y.size(0)
                test_acc = (torch.sigmoid(pred_test).round() == test_y).sum().cpu().data.numpy().item() / test_y.size(0)

            ## Uncomment to plot the decision boundaries
            # plot_decision_boundaries(model, n_node, n_poly, 1-test_acc, method='all', depth=depth)

            losses_list.append(losses)
            num_pars.append(n_par)
            num_poly.append(n_poly)

            train_loss_list.append(train_loss.item())
            test_loss_list.append(test_loss.item())
            train_acc_list.append(1-train_acc)
            test_acc_list.append(1-test_acc)
            hellinger_list.append(hellinger_loss)
            gini_train.append(gini_impurity_train)
            gini_test.append(gini_impurity_test) 

            avg_stab = 0 #compute_avg_stability(model, hybrid_sets)
            bias, var = 0,0 #compute_bias_variance(model, test_x, test_y, T=100)
            avg_stab_list.append(avg_stab)
            bias_list.append(bias)
            var_list.append(var)

        rep_full_list.append([losses_list, train_loss_list, test_loss_list, train_acc_list, test_acc_list, hellinger_list, num_poly, gini_train, gini_test, avg_stab_list, bias_list, var_list])
        penultimate_vars_reps.append(penultimate_vars)

    result.num_pars = num_pars
    [result.full_loss_list, result.train_loss_list, result.test_loss_list, result.test_err_list, result.train_err_list, result.hellinger_list, result.poly_list, result.gini_train, result.gini_test, result.avg_stab, result.bias, result.var] = extract_losses(rep_full_list)
     
    result.penultimate_vars_reps = penultimate_vars_reps

    return result 

# Losses
def extract_losses(rep_full_list):
    """
     Extract and return the metrics from a list of losses
    """
    full_loss_list = []
    for losses_list, *_ in rep_full_list:
        final_loss = [l[-1] for l in losses_list]
        full_loss_list.append(final_loss)
 
    full_loss_list = np.array(full_loss_list)

    return_list = [full_loss_list]
    # test_loss_list = np.array([ee[2] for ee in rep_full_list])
    # train_loss_list = np.array([ee[1] for ee in rep_full_list])
    # test_err_list = np.array([ee[4] for ee in rep_full_list])
    # train_err_list = np.array([ee[3] for ee in rep_full_list])
    # hellinger_list = np.array([ee[5] for ee in rep_full_list])
    # poly_list = np.array([ee[6] for ee in rep_full_list])
    # gini_train = np.array([ee[7] for ee in rep_full_list])
    # gini_test = np.array([ee[8] for ee in rep_full_list])
    
    for idx in range(1, len(rep_full_list[0])):
        return_list.append( np.array(np.array([err[idx] for err in rep_full_list]) ))

    return return_list
    # if(len(rep_full_list[0]) > 9):
    #     avg_stab = np.array([ee[9] for ee in rep_full_list])
    #     # avg_stab = avg_stab
    #     bias = np.array([ee[10] for ee in rep_full_list])#avg_stab[:,:,1]
    #     var = np.array([ee[11] for ee in rep_full_list])#avg_stab[:,:,2]
    #     # avg_stab = avg_stab[:,:,0]

    #     return [full_loss_list, test_loss_list, train_loss_list, test_err_list, train_err_list, hellinger_list, poly_list, gini_train, gini_test, avg_stab, bias, var] 
    # return [full_loss_list, test_loss_list, train_loss_list, test_err_list, train_err_list, hellinger_list, poly_list, gini_train, gini_test]


# Average stability
def compute_avg_stability(model, hybrid_set):
    """
     Compute the average stability of a model 
     based on https://mlstory.org/generalization.html#algorithmic-stability
    """
    stab_dif = 0
    N = len(hybrid_set)
    loss_func = torch.nn.BCEWithLogitsLoss()

    for i in range(N):
        model_hybrid = copy.deepcopy(model)

        ghost_loss = loss_func(model(hybrid_set[i][0]), hybrid_set[i][1])
        loss = train_model(model_hybrid, hybrid_set[i][0], hybrid_set[i][1])
        stab_dif += ( ghost_loss.detach().cpu().numpy().item() - loss[-1] )

    return stab_dif / N

# Gini impurity 
def gini_impurity(P1=0, P2=0):
    denom = P1 + P2
    Ginx = 2 * (P1/denom) * (P2/denom)
    return(Ginx)

def gini_impurity_mean(polytope_memberships, predicts):
    """
     Compute the mean Gini impurity based on
     the polytope membership of the points and 
     the model prediction of the labels.
    """
    gini_mean_score = []
    
    for l in np.unique(polytope_memberships):
        
        cur_l_idx = predicts[polytope_memberships==l]
        pos_count = np.sum(cur_l_idx)
        neg_count = len(cur_l_idx) - pos_count
        gini = gini_impurity(pos_count, neg_count)
        gini_mean_score.append(gini) 

    return np.array(gini_mean_score).mean()

def gini_impurity_list(polytope_memberships, predicts):
    """
     Computes the Gini impurity same as above
     but returns the whole list
    """
    gini_score = np.zeros(polytope_memberships.shape)

    for l in np.unique(polytope_memberships):        
        idx = np.where(polytope_memberships==l)[0]
        cur_l_idx = predicts[polytope_memberships==l]
        pos_count = np.sum(cur_l_idx)
        neg_count = len(cur_l_idx) - pos_count
        gini = gini_impurity(pos_count, neg_count)
        gini_score[idx] = (gini) 

    return np.array(gini_score)#.mean()       

# Hellinger distance
def hellinger_explicit(p, q):
    """Hellinger distance between two discrete distributions.
       Same as original version but without list comprehension
    """
    return np.mean(np.sqrt(np.sum((np.sqrt(p) - np.sqrt(q)) ** 2, axis = 1)) / np.sqrt(2))

def pdf(x):
    mu01, mu02, mu11, mu12 = [[-1, -1], [1, 1], [-1, 1], [1, -1]]
   
    cov = 1 * np.eye(2)
    inv_cov = np.linalg.inv(cov) 

    p0 = (
        np.exp(-(x - mu01)@inv_cov@(x-mu01).T) 
        + np.exp(-(x - mu02)@inv_cov@(x-mu02).T)
    )/(2*np.pi*np.sqrt(np.linalg.det(cov)))

    p1 = (
        np.exp(-(x - mu11)@inv_cov@(x-mu11).T) 
        + np.exp(-(x - mu12)@inv_cov@(x-mu12).T)
    )/(2*np.pi*np.sqrt(np.linalg.det(cov)))

    return [p1/(p0+p1), p0/(p0+p1)]  

# Polytope functions
def get_polytopes(model, train_x, penultimate=False):
    """
     Returns the polytopes.
     Points that has same activations values after fed to the model
      belong to the same polytope.
    """
    polytope_memberships = []
    last_activations = train_x.cpu().numpy()
    penultimate_act = None
    layers = [module for module in model.modules() if type(module) == torch.nn.Linear]
    
    for layer_id, layer in enumerate(layers):
        weights, bias = layer.weight.data.detach().cpu().numpy(), layer.bias.data.detach().cpu().numpy()
        preactivation = np.matmul(last_activations, weights.T) + bias
        if layer_id == len(layers) - 1:
            binary_preactivation = (preactivation > 0.5).astype('int')
        else:
            binary_preactivation = (preactivation > 0).astype('int')
        polytope_memberships.append(binary_preactivation)
        last_activations = preactivation * binary_preactivation

        if penultimate and layer_id == len(layers) - 1:
            penultimate_act = last_activations
    polytope_memberships = [np.tensordot(np.concatenate(polytope_memberships, axis = 1), 2 ** np.arange(0, np.shape(np.concatenate(polytope_memberships, axis = 1))[1]), axes = 1)]
    
    if penultimate:
        return polytope_memberships, penultimate_act
    return polytope_memberships, last_activations

def plot_decision_boundaries(model, num_node, num_poly, err, method='contour', depth=True):
    """
     Plot the decision boundaries of the model 
    """
    # create grid to evaluate model
    x_min, x_max = -5,5 
    y_min, y_max = -5,5 
    XX, YY = np.meshgrid(np.arange(x_min, x_max, (x_max - x_min) / 50),
                         np.arange(y_min, y_max, (y_max - y_min) / 50))

    XY = np.vstack([XX.ravel(), YY.ravel()]).T
    
    poly_m, activations = get_polytopes(model, torch.FloatTensor(XY))
    
    with torch.no_grad():
        pred = model(torch.FloatTensor(XY).cuda())
        pred = torch.sigmoid(pred).detach().cpu().numpy()

    gini_list = gini_impurity_list(poly_m[0], np.round(pred))

    Z = poly_m[0].reshape(XX.shape)
    bins = np.arange(0,len(poly_m[0]))
    act_bin = np.digitize(poly_m[0], bins)
    
    if method == 'all':
        fig, ax = plt.subplots(1, 3, figsize=(21, 5))
        for a in ax:
            a.axes.xaxis.set_visible(False)
            a.axes.yaxis.set_visible(False)
    else:
        fig, ax = plt.subplots(1, 1, figsize=(7, 5))
        ax.axes.xaxis.set_visible(False)
        ax.axes.yaxis.set_visible(False)
    if method == 'surface' or method=='all':
        m = poly_m[0]
        m = minmax_scale(m, feature_range=(0, 1), axis=0, copy=True)
        my_col = cm.tab20b(m.reshape(XX.shape))

        if method == 'surface':
            fig = plt.figure(figsize=(7, 5))
            ax = fig.add_subplot(111, projection='3d')
        else:
            ax = fig.add_subplot(132, projection='3d')
        
        ax.view_init(elev=45., azim=15)
        ax.plot_surface(X=XX, Y=YY, Z=pred.reshape(XX.shape), facecolors=my_col, linewidth=0, antialiased=False, rstride=1, cstride=1)        
        # Get rid of the panes
        ax.w_xaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.w_yaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))
        ax.w_zaxis.set_pane_color((1.0, 1.0, 1.0, 0.0))

        # Get rid of the spines
        ax.w_xaxis.line.set_color((1.0, 1.0, 1.0, 0.0))
        ax.w_yaxis.line.set_color((1.0, 1.0, 1.0, 0.0))
        ax.w_zaxis.line.set_color((1.0, 1.0, 1.0, 0.0))

        # Get rid of the ticks
        ax.set_xticks([]) 
        ax.set_yticks([]) 
        ax.set_zticks([])
        ax.set_title("Generalization error: %.4f" % err)

    if method == 'colormesh' or method=='all':
        if method == 'all':
            ax = fig.add_subplot(131)
        plt.pcolormesh(XX, YY, Z, cmap="PRGn")
        ax.set_xticks([]) 
        ax.set_yticks([]) 

        ax.set_title("Nodes: " + str(num_node) + "; # of activated regions: " + str(num_poly))

    # if method == 'contour' or method=='all':
    #     if method == 'all':
    #         ax = fig.add_subplot(142)
        
    #     plt.contourf(XX, YY, Z, cmap="tab20b",  vmin = np.min(Z), vmax = np.max(Z))
    #     ax.set_title("Nodes: " + str(num_node) + "; # of activated regions: " + str(num_poly))
    #     ax.set_xticks([]) 
    #     ax.set_yticks([]) 
    
    if method == 'gini' or method=='all':
        if method == 'all':
            ax = fig.add_subplot(133)
        # gini_Z = minmax_scale(gini_list, feature_range=(0, 1), axis=0, copy=True)
        gini_Z = gini_list.reshape(XX.shape)
        plt.pcolormesh(XX, YY, gini_Z, cmap="Reds", vmin = 0, vmax = 0.5)
        cbar = plt.colorbar(ticks=np.linspace(0, 0.5, 2))
        cbar.ax.set_title('gini index', fontsize=12, pad=12)
        cbar.set_ticklabels(['0','0.5'])
        ax.set_title("Mean: %.4f" % np.mean(gini_list) )
        ax.set_xticks([]) 
        ax.set_yticks([]) 

    exp = "depth" if depth else "width"
    os.makedirs('polytopes/', exist_ok=True)
    plt.savefig('polytopes/xor_%s_%s_%04d.png'%(exp,method,num_node))
    # plt.show()


# Plot the result      
def plot_results(results):
    """
     Generate the DeepNet: Increasing Depth vs Increasing Width figure.
     results should consist the `Increasing Width` and `Increasing Depth` results, respectively.
    """

    sns.set()
    fontsize=20
    ticksize=20

    bayes_err = 0.25

    #Figure params
    fontsize = 22
    ticksize = 20
    linewidth = 2
    fig, axes = plt.subplots(figsize=(14,20), nrows=4, ncols=2, sharex='col', sharey='row')
    # plt.figure(
    plt.tick_params(labelsize=ticksize)
    plt.tight_layout()

    titles = ['DeepNet: Increasing Width', 'DeepNet: Increasing Depth', 'DeepNet: Increasing Width (5 layers)']


    ## Average Stability, Bias and Variance
    for i in range(len(results)):
        result = results[i]
        
        ## You can choose the panels to display
        # metric_list = [(result.train_err_list, result.test_err_list), (result.train_loss_list, result.test_loss_list), result.penultimate_vars_reps, result.poly_list, result.briers_list, (result.gini_train, result.gini_test), result.avg_stab, result.bias, result.var]
        # metric_ylab = ["Generalization Error", "Cross-Entropy Loss", "Variance of last activation", "Activated regions", "Hellinger distance", "Gini impurity", "Average stability", "Average Bias", "Average Variance"]
        metric_list = [(result.train_err_list, result.test_err_list), (result.train_loss_list, result.test_loss_list), (result.gini_train, result.gini_test),  result.poly_list]
        metric_ylab = ["Generalization Error", "Cross-Entropy Loss", "Gini impurity", "Activated regions", "Hellinger distance"]

        for j, metric in enumerate(metric_list):
            ax = axes[j, i]
            if isinstance(metric, tuple):
                ax.plot(result.num_pars, np.median(metric[0], 0).clip(min=0), label = 'Train', linewidth=2)
                ax.fill_between(result.num_pars, np.percentile(metric[0], 25, axis=0).clip(min=0), np.percentile(metric[0], 75, axis=0), alpha=0.2)
                ax.plot(result.num_pars, np.median(metric[1], 0), label = 'Test', color='red', linewidth=2)
                ax.fill_between(result.num_pars, np.percentile(metric[1], 25, axis=0).clip(min=0), np.percentile(metric[1], 75, axis=0), alpha=0.2)
            else:
                ax.plot(result.num_pars, np.median(metric, 0).clip(min=0), linewidth=2)
                ax.fill_between(result.num_pars, np.percentile(metric, 25, axis=0).clip(min=0), np.percentile(metric, 75, axis=0), alpha=0.2)

            ax.axvline(x=1000, color='gray', alpha=0.6)
            if j == 0:
                ax.set_title(titles[i], fontsize = fontsize+2)
                # ax.axhline(y=bayes_err, color='gray', linestyle='--')
                
            if i==0:
                ax.set_ylabel(metric_ylab[j], fontsize = fontsize)

            ax.set_xscale("log")
        #     ax = plt.gca()
            ax.locator_params(nbins=6, axis='y')
            # ax.locator_params(nbins=6, axis='x')
            ax.tick_params(axis='both', which='major', labelsize=ticksize)

    lines, labels = ax.get_legend_handles_labels()    
    plt.legend( lines, labels, loc = 'best', bbox_to_anchor = (0.0,-0.009,1,1),
                bbox_transform = plt.gcf().transFigure , fontsize=fontsize-5, frameon=False)
        
    # plt.text(2.8, -0.0490, 'Total parameters', ha='center', fontsize=fontsize)
    sns.despine();    
    os.makedirs('results', exist_ok=True)     
    plt.savefig('results/DeepNet.pdf', bbox_inches='tight')


"""
  Example to run the `Increasing Depth` vs `Increasing Width` experiments
  and plot the figure.
"""
## Example
# result_d = run_experiment(depth=True, iterations=20, reps=1)
# result_w = run_experiment(depth=False, iterations=70, reps=1)
# results = [result_w, result_d]
# plot_results(results)
