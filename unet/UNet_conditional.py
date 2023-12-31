import torch
from torch import nn

from unet.UNet import MyUNet


class UNet_conditional(MyUNet):

    # In the base of our U-Net, we only add a embedding for label
    # We add label embedding directly with the time embedding, so all the part in the network have the information about the label
    
    def __init__(self, n_steps=1000, time_emb_dim=100, nb_classes=None):
        super().__init__(n_steps, time_emb_dim)
        if nb_classes is not None:
            self.label_emb = nn.Embedding(nb_classes, time_emb_dim)

    def forward(self, x, t, y=None):
        t = self.time_embed(t)
        t = torch.squeeze(t)

        if y is not None:
            t += self.label_emb(y)
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
