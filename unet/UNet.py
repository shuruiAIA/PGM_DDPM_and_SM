import torch
from torch import nn

# For the dataset MNIST, we try to use the U-NET to replace the network
def sinusoidal_embedding(n, d):
    # Returns the standard positional embedding
    embedding = torch.tensor([[i / 10_000 ** (2 * j / d) for j in range(d)] for i in range(n)])
    sin_mask = torch.arange(0, n, 2)

    embedding[sin_mask] = torch.sin(embedding[sin_mask])
    embedding[1 - sin_mask] = torch.cos(embedding[sin_mask])

    return embedding


class MyBlock(nn.Module):
    def __init__(self, shape, in_c, out_c, kernel_size=3, stride=1, padding=1, activation=None, normalize=True):
        super(MyBlock, self).__init__()
        self.ln = nn.LayerNorm(shape)
        self.conv1 = nn.Conv2d(in_c, out_c, kernel_size, stride, padding)
        self.conv2 = nn.Conv2d(out_c, out_c, kernel_size, stride, padding)
        self.activation = nn.SiLU() if activation is None else activation
        self.normalize = normalize

    def forward(self, x):
        out = self.ln(x) if self.normalize else x
        out = self.conv1(out)
        out = self.activation(out)
        out = self.conv2(out)
        out = self.activation(out)
        return out
    

class MyUNet(nn.Module):
    # Here is a network with 3 down and 3 up with the MyBlock
    # You can see a graphical explanation in the appendix of our report
    def __init__(self, n_steps=1000, time_emb_dim=100):
        super().__init__()

        # Sinusoidal embedding
        self.time_embed = nn.Embedding(n_steps, time_emb_dim)
        self.time_embed.weight.data = sinusoidal_embedding(n_steps, time_emb_dim)
        self.time_embed.requires_grad_(False)

        # First half
        self.te1 = self._make_te(time_emb_dim, 1)
        self.b1 = nn.Sequential(
            MyBlock((1, 28, 28), 1, 10),
            MyBlock((10, 28, 28), 10, 10),
            MyBlock((10, 28, 28), 10, 10)
        )
        self.down1 = nn.Conv2d(10, 10, 4, 2, 1)

        self.te2 = self._make_te(time_emb_dim, 10)
        self.b2 = nn.Sequential(
            MyBlock((10, 14, 14), 10, 20),
            MyBlock((20, 14, 14), 20, 40),
            MyBlock((40, 14, 14), 40, 40)
        )
        self.down2 = nn.Conv2d(40, 40, 4, 2, 1)

        self.te3 = self._make_te(time_emb_dim, 40)
        self.b3 = nn.Sequential(
            MyBlock((40, 7, 7), 40, 80),
            MyBlock((80, 7, 7), 80, 160),
            MyBlock((160, 7, 7), 160, 160)
        )
        self.down3 = nn.Sequential(
            nn.Conv2d(160, 160, 2, 1),
            nn.SiLU(),
            nn.Conv2d(160, 160, 4, 2, 1)
        )

        # Bottleneck
        self.te_mid = self._make_te(time_emb_dim, 160)
        self.b_mid = nn.Sequential(
            MyBlock((160, 3, 3), 160, 160),
            MyBlock((160, 3, 3), 160, 160),
            MyBlock((160, 3, 3), 160, 160)
        )

        # Second half
        self.up1 = nn.Sequential(
            nn.ConvTranspose2d(160, 160, 4, 2, 1),
            nn.SiLU(),
            nn.ConvTranspose2d(160, 160, 2, 1)
        )

        self.te4 = self._make_te(time_emb_dim, 320)
        self.b4 = nn.Sequential(
            MyBlock((320, 7, 7), 320, 160),
            MyBlock((160, 7, 7), 160, 80),
            MyBlock((80, 7, 7), 80, 80)
        )

        self.up2 = nn.ConvTranspose2d(80, 40, 4, 2, 1)
        self.te5 = self._make_te(time_emb_dim, 80)
        self.b5 = nn.Sequential(
            MyBlock((80, 14, 14), 80, 40),
            MyBlock((40, 14, 14), 40, 20),
            MyBlock((20, 14, 14), 20, 20)
        )

        self.up3 = nn.ConvTranspose2d(20, 10, 4, 2, 1)
        self.te_out = self._make_te(time_emb_dim, 20)
        self.b_out = nn.Sequential(
            MyBlock((20, 28, 28), 20, 20),
            MyBlock((20, 28, 28), 20, 10),
            MyBlock((10, 28, 28), 10, 10, normalize=False)
        )

        self.conv_out = nn.Conv2d(10, 1, 3, 1, 1)

    def forward(self, x, t):
        # x is (N, 2, 28, 28) (image with positional embedding stacked on channel dimension)
        t = self.time_embed(t)
        n = len(x)
        out1 = self.b1(x + self.te1(t).reshape(n, -1, 1, 1))  
        out2 = self.b2(self.down1(out1) + self.te2(t).reshape(n, -1, 1, 1))
        out3 = self.b3(self.down2(out2) + self.te3(t).reshape(n, -1, 1, 1))

        out_mid = self.b_mid(self.down3(out3) + self.te_mid(t).reshape(n, -1, 1, 1))

        out4 = torch.cat((out3, self.up1(out_mid)), dim=1)
        out4 = self.b4(out4 + self.te4(t).reshape(n, -1, 1, 1))

        out5 = torch.cat((out2, self.up2(out4)), dim=1)
        out5 = self.b5(out5 + self.te5(t).reshape(n, -1, 1, 1))

        out = torch.cat((out1, self.up3(out5)), dim=1)
        out = self.b_out(out + self.te_out(t).reshape(n, -1, 1, 1))

        out = self.conv_out(out)

        return out

    def _make_te(self, dim_in, dim_out):
        return nn.Sequential(nn.Linear(dim_in, dim_out), nn.SiLU(), nn.Linear(dim_out, dim_out))
