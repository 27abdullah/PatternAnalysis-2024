from dataset import *
import torch
from torch.utils.data import DataLoader
import torchio as tio
from utils import *
from modules import *
from monai.losses.dice import DiceLoss
import nibabel as nib

device = torch.device('cuda' if torch.cuda.is_available() else 'mps')

if IS_RANGPUR:
    images_path = "/home/groups/comp3710/HipMRI_Study_open/semantic_MRs/"
    masks_path = "/home/groups/comp3710/HipMRI_Study_open/semantic_labels_only/"
    epochs = 50
    batch_size = 5
else:
    images_path = "./data/semantic_MRs_anon/"
    masks_path = "./data/semantic_labels_anon/"
    epochs = 10
    batch_size = 2

# Data parameters
batch_size = batch_size
shuffle = True
num_workers = 2
epochs = epochs
background = True

# Model parameters
in_channels = 1 # greyscale
n_classes = 6 # 6 different values in mask
base_n_filter = 8

# Optimizer parameters
lr = 1e-3
weight_decay = 1e-2

# Scheduler parameters
step_size = 10
gamma = 0.1


# Test loop
def validate(model, data_loader):
    criterion = DiceLoss()

    model.eval()  
    test_loss = 0.0
    dice_scores = [0] * n_classes 

    with torch.no_grad():
        for i, data in enumerate(data_loader):  
            dice_score = DiceLoss()
            # inputs, masks, affine = data
            inputs, masks = data
            inputs, masks = inputs.to(device), masks.to(device)
            if masks.dtype != torch.long:
                masks = masks.long()

            # Forward pass
            _, predictions, logits = model(inputs)
            masks = masks.view(-1)  # Flatten masks
            masks = F.one_hot(masks, num_classes=6) 

            # Group categories for masks and labels
            for i in range(n_classes):
                mask = F.one_hot( masks[:, i].long(), num_classes=2)
                prediction = F.one_hot(predictions[:, i].long(), num_classes=2)
                dice_scores[i] += dice_score(prediction, mask)

            # Calculate loss
            loss = criterion(logits, masks)
            test_loss += loss.item()

            # predictions = torch.argmax(predictions, dim=1)
            # prediction = predictions.view(128, 128, 128).cpu().numpy()
            # affine = affine.cpu().numpy()[0]
            # print(affine.shape, prediction.shape)
            # nib.save(nib.Nifti1Image(prediction, affine), f"prediction_{i}.nii.gz")
            
    # Average loss and dice score
    avg_test_loss = test_loss / len(data_loader)

    print(f"Test Loss: {avg_test_loss}")
    print(f"Average Dice Score: {list(map(lambda x: 1 - float(x / len(data_loader)), dice_scores))}")



if __name__ == '__main__':
    # Load and process data
    transforms = tio.Compose([
        tio.RescaleIntensity((0, 1)),
        tio.RandomFlip(),
        tio.Resize((128,128,128)),
        tio.RandomAffine(degrees=10),
        tio.RandomElasticDeformation(),
        tio.ZNormalization(),
    ])
    
    valid_dataset = ProstateDataset3D(images_path, masks_path, transforms, "valid")
    valid_dataloader = DataLoader(valid_dataset, batch_size=1, shuffle=shuffle, num_workers=num_workers)

    mode = "train" if IS_RANGPUR else "debug"
    train_dataset = ProstateDataset3D(images_path, masks_path, transforms, mode)
    train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)

    # Model
    model = Modified3DUNet(in_channels, n_classes, base_n_filter)
    model.to(device)
    model.apply(init_weights)
        
    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    # Scheduler
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=step_size, gamma=gamma)

    # Loss function
    criterion = DiceLoss(include_background=background)

    # Training loop
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        for i, data in enumerate(train_dataloader):
            # inputs, masks, affine = data
            inputs, masks = data
            inputs, masks = inputs.to(device), masks.to(device)

            if masks.dtype != torch.long:
                masks = masks.long()
            masks = masks.view(-1)  # [batch * l * w * h]
            masks = F.one_hot(masks, num_classes=6) # [batch * l * w * h, 6]
            
            optimizer.zero_grad()
            sigmoid_logits, predictions, logits = model(inputs) # All shapes: [batch * l * w * h, 6]
            loss = criterion(logits, masks)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
        
        scheduler.step()
        if epoch % 3 == 0:
            validate(model, valid_dataloader)
        print(f"Epoch {epoch+1}/{epochs}, Loss: {running_loss/len(valid_dataloader)}")

    # save model
    torch.save(model.state_dict(), f'model_lr_{lr}_e_{epochs}_bg_{background}_bs{batch_size}.pth')
    validate(model, valid_dataloader)