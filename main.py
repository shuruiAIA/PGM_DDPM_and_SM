import argparse

import numpy as np
import matplotlib.pyplot as plt

import torch
from torch.nn import functional as F
import torchvision
from torchvision import transforms
from tqdm.auto import tqdm

from unet.UNet import MyUNet
from unet.UNet_conditional import UNet_conditional
from ddpm.ddpm import DDPM
from ddpm.ddpm_conditional import DDPM_conditional
from ddpm.ddpm_cold import MedianBlur, ConvolutionBlur, SuperResolution
from score.score_utils import AnnealedLangevinDynamic
from score.score_model import Score_Model


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def training_loop(model, dataloader, optimizer, num_epochs, num_timesteps, device=device):
    """Training loop for DDPM"""

    global_step = 0
    losses = []
    
    for epoch in range(num_epochs):
        model.train()
        progress_bar = tqdm(total=len(dataloader))
        progress_bar.set_description(f"Epoch {epoch}")
        for step, batch in enumerate(dataloader):
            batch = batch[0].to(device)
            noise = torch.randn(batch.shape).to(device)
            timesteps = torch.randint(0, num_timesteps, (batch.shape[0],)).long().to(device)

            noisy = model.add_noise(batch, noise, timesteps)
            noise_pred = model.reverse(noisy, timesteps)
            loss = F.mse_loss(noise_pred, noise)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            progress_bar.update(1)
            logs = {"loss": loss.detach().item(), "step": global_step}
            losses.append(loss.detach().item())
            progress_bar.set_postfix(**logs)
            global_step += 1
        progress_bar.close()

def training_loop_conditional(model, dataloader, optimizer, num_epochs, num_timesteps, nb_classes=10, device=device):
    """Training loop for DDPM version conditional"""
    global_step = 0
    losses = []
    
    for epoch in range(num_epochs):
        model.train()
        progress_bar = tqdm(total=len(dataloader))
        progress_bar.set_description(f"Epoch {epoch}")
        for step, (images, labels) in enumerate(dataloader):
            images = images.to(device)
            labels = labels.to(device)
            noise = torch.randn(images.shape).to(device)
            timesteps = torch.randint(0, num_timesteps, (images.shape[0],)).long().to(device)

            noisy = model.add_noise(images, noise, timesteps)
            noise_pred = model.reverse(noisy, timesteps, labels)
            loss = F.mse_loss(noise_pred, noise)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            progress_bar.update(1)
            logs = {"loss": loss.detach().item(), "step": global_step}
            losses.append(loss.detach().item())
            progress_bar.set_postfix(**logs)
            global_step += 1
        progress_bar.close()

def training_loop_cold(model, dataloader, optimizer, num_epochs, num_timesteps, device=device):
    """Training loop for cold diffusion"""

    global_step = 0
    losses = []
    
    for epoch in range(num_epochs):
        model.train()
        progress_bar = tqdm(total=len(dataloader))
        progress_bar.set_description(f"Epoch {epoch}")
        for step, batch in enumerate(dataloader):
            batch = batch[0].to(device)
   
            timesteps = torch.randint(1, num_timesteps, (batch.shape[0],)).long().to(device)

            blured = model.forward_process(batch, timesteps)
            image_pred = model.reverse(blured, timesteps)
            loss = F.mse_loss(image_pred, batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            progress_bar.update(1)
            logs = {"loss": loss.detach().item(), "step": global_step}
            losses.append(loss.detach().item())
            progress_bar.set_postfix(**logs)
            global_step += 1
        progress_bar.close()

def training_loop_score(model, dataloader, optimizer, num_epochs, device=device):
    """Training loop for score matching"""

    global_step = 0
    losses = []
    
    for epoch in range(num_epochs):
        model.train()
        progress_bar = tqdm(total=len(dataloader))
        progress_bar.set_description(f"Epoch {epoch}")
        for step, batch in enumerate(dataloader):
            batch = batch[0].to(device)

            loss = model.loss_fn(batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            progress_bar.update(1)
            logs = {"loss": loss.detach().item(), "step": global_step}
            losses.append(loss.detach().item())
            progress_bar.set_postfix(**logs)
            global_step += 1
        progress_bar.close()
    

def generate_image(ddpm, sample_size, channel, height, width):
    """Generate the image from the Gaussian noise"""

    frames = []
    frames_mid = []
    with torch.no_grad():
        timesteps = list(range(ddpm.num_timesteps))[::-1]
        sample = torch.randn(sample_size, channel, height, width).to(device)
        
        for i, t in enumerate(tqdm(timesteps)):
            time_tensor = (torch.ones(sample_size, 1) * t).long().to(device)
            residual = ddpm.reverse(sample, time_tensor).to(device)
            sample = ddpm.step(residual, time_tensor[0], sample)

            if t==500:
                sample_squeezed = torch.squeeze(sample)
                for i in range(sample_size):
                    frames_mid.append(sample_squeezed[i].detach().cpu().numpy())

        sample = torch.squeeze(sample)
        for i in range(sample_size):
            frames.append(sample[i].detach().cpu().numpy())
    return frames, frames_mid

def generate_image_conditional(ddpm, labels, sample_size, channel, height, width):
    """Generate the image for the version conditional"""

    frames = []
    frames_mid = []
    with torch.no_grad():
        timesteps = list(range(ddpm.num_timesteps))[::-1]
        sample = torch.randn(sample_size, channel, height, width).to(device)
        
        for i, t in enumerate(tqdm(timesteps)):
            time_tensor = (torch.ones(sample_size, 1) * t).long().to(device)
            predicted_noise = ddpm.reverse(sample, time_tensor, labels).to(device)
            sample = ddpm.step(predicted_noise, time_tensor[0], sample)

            if t==500:
                sample_squeezed = torch.squeeze(sample)
                for i in range(sample_size):
                    frames_mid.append(sample_squeezed[i].detach().cpu().numpy())

        sample = torch.squeeze(sample)
        for i in range(sample_size):
            frames.append(sample[i].detach().cpu().numpy())
    return frames, frames_mid

def generate_image_cold(model, images, algoindex):
    """Generate the image from the final blured image for cold diffusion"""

    frames = []
    sample_size = images.shape[0]
    with torch.no_grad():
        time_tensor = (torch.ones(sample_size) * model.num_timesteps).long().to(device)
        blured = model.forward_process(images, time_tensor).to(device)
    
        timesteps = list(range(1, model.num_timesteps))[::-1]
        
        for i, t in enumerate(tqdm(timesteps)):
            if t>1:
                time_tensor = (torch.ones(sample_size, 1) * t).long().to(device)
                if algoindex==1:
                    blured = model.restore_step_algo1(blured, time_tensor)
                if algoindex==2:
                    blured = model.restore_step_algo2(blured, time_tensor)
            else:
                time_tensor = (torch.ones(sample_size, 1) * t).long().to(device)
                blured = model.reverse(blured, time_tensor)

        for i in range(sample_size):
            frames.append(blured[i].detach().cpu().numpy())
    return frames

def show_images(images, title="", pixel=28, channel=1):
    """Shows the provided images as sub-pictures in a square"""

    # Converting images to CPU numpy arrays
    if type(images) is torch.Tensor:
        images = images.detach().cpu().numpy()

    # Defining number of rows and columns
    fig = plt.figure(figsize=(8, 8))
    rows = int(len(images) ** (1 / 2))
    cols = round(len(images) / rows)

    # Populating figure with sub-plots
    idx = 0
    for r in range(rows):
        for c in range(cols):
            fig.add_subplot(rows, cols, idx + 1)

            if idx < len(images):
                plt.imshow(images[idx].reshape(pixel, pixel, channel), cmap='gray')
                idx += 1
    fig.suptitle(title, fontsize=30)
    # Showing the figure
    plt.savefig(f"figure/{title}.jpg")
    plt.show()

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment_name", type=str, default="ddpm", help="ddpm/ddpm_conditional/cold_median/cold_kernel/cold_resolution/score")
    config = parser.parse_args()

    learning_rate = 1e-3
    dataset = torchvision.datasets.MNIST(root='data', train=True, transform=transforms.ToTensor(), download=True)
    dataloader = torch.utils.data.DataLoader(dataset=dataset, batch_size=128, shuffle=True)

    if config.experiment_name == "ddpm":
        num_epochs = 200
        num_timesteps = 1000
        network = MyUNet()
        model = DDPM(network, num_timesteps, beta_start=0.0001, beta_end=0.02, device=device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate)
        training_loop(model, dataloader, optimizer, num_epochs, num_timesteps, device=device)
        generated, generated_mid = generate_image(model, 100, 1, 28, 28)
        show_images(generated_mid, "Mid result")
        show_images(generated, "Final result")

    if config.experiment_name == "ddpm_conditional":
        num_epochs = 200
        num_timesteps = 1000
        network = UNet_conditional(nb_classes=10)
        model = DDPM_conditional(network, num_timesteps, beta_start=0.0001, beta_end=0.02, device=device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate)
        training_loop_conditional(model, dataloader, optimizer, num_epochs, num_timesteps, device=device)
        labels = torch.arange(10).long().to(device).repeat(10)
        generated, generated_mid = generate_image_conditional(model, labels, 100, 1, 28, 28)
        show_images(generated_mid, "Mid result")
        show_images(generated, "Final result")

    if config.experiment_name == "cold_median":
        num_epochs = 100
        num_timesteps = 100
        num_timesteps_generate = 100
        kernel_size = 3

        network = MyUNet()
        model = MedianBlur(network, num_timesteps, num_timesteps_generate, kernel_size, device=device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate)
        training_loop_cold(model, dataloader, optimizer, num_epochs, num_timesteps, device=device)

        images = dataset.data[0:100].unsqueeze(1)
        generated_1 = generate_image_cold(model, images, 1)
        generated_2 = generate_image_cold(model, images, 2)
        time_tensor = (torch.ones(100, 1) * model.num_timesteps).long()
        blured_final = model.forward_process(images, time_tensor)
        show_images(generated_1, "Final result1")
        show_images(generated_2, "Final result2")
        show_images(blured_final, "Final blured")


    if config.experiment_name == "cold_kernel":
        num_epochs = 50
        num_timesteps = 30
        num_timesteps_generate = 25
        # Here we can choose the kernel
        kernel = 1/9*np.array([[1, 1, 1],[1, 1, 1],[1, 1, 1]]) # Mean kernel
        # kernel = 1/16*np.array([[1, 2, 1],[2, 4, 2],[1, 2, 1]]) # Gaussian kernel

        network = MyUNet()
        model = ConvolutionBlur(network, num_timesteps, num_timesteps_generate, kernel, device=device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate)
        training_loop_cold(model, dataloader, optimizer, num_epochs, num_timesteps, device=device)

        images = dataset.data[0:100].unsqueeze(1)
        generated_1 = generate_image_cold(model, images, 1)
        generated_2 = generate_image_cold(model, images, 2)
        time_tensor = (torch.ones(100, 1) * model.num_timesteps).long()
        blured_final = model.forward_process(images, time_tensor)
        show_images(generated_1, "Final result1")
        show_images(generated_2, "Final result2")
        show_images(blured_final, "Final blured")


    if config.experiment_name == "cold_resolution":
        num_epochs = 50
        num_timesteps = 8

        network = MyUNet()
        model = SuperResolution(network, num_timesteps, device=device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=learning_rate)
        training_loop_cold(model, dataloader, optimizer, num_epochs, num_timesteps, device=device)

        images = dataset.data[0:100].unsqueeze(1)
        generated_1 = generate_image_cold(model, images, 1)
        generated_2 = generate_image_cold(model, images, 2)
        time_tensor = (torch.ones(100, 1) * model.num_timesteps).long()
        blured_final = model.forward_process(images, time_tensor)
        show_images(generated_1, "Final result1")
        show_images(generated_2, "Final result2")
        show_images(blured_final, "Final blured")
    
    if config.experiment_name == "score":
        print("Launch the score matching experiment")
        num_epochs = 300
        sampling_number = 100
        only_final = True
        # epsilon of step size
        eps = 1.5e-5
        # sigma min and max of Langevin dynamic
        sigma_min = 0.005
        sigma_max = 10
        # Langevin step size and Annealed size
        n_steps = 100
        annealed_step = 100

        # network = MyUNet(n_steps=n_steps)
        model = Score_Model(network, device, n_steps, sigma_min, sigma_max)
        optim = torch.optim.Adam(model.parameters(), lr = learning_rate)
        training_loop_score(model, dataloader, optim, num_epochs, device)
        samplingMethod = AnnealedLangevinDynamic(sigma_min, sigma_max, n_steps, annealed_step, model, device, eps=eps)
        samples = samplingMethod.sampling(sampling_number, only_final)
        show_images(samples, "ScoreBased Model", pixel=28)
